from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from ..process_store import ProcessConfig
from ..utils import dir_size_bytes
from .managers import BackupEntry, BackupManager, ConsoleRelay, PluginManager, ProcessLogger, ProcessRunner

if TYPE_CHECKING:
    import discord

    from ...discord.client import DisManagerClient


class ManagedProcess:
    """High-level coordinator for a managed process, its runner, relay, plugins, and backups."""

    _loop: asyncio.AbstractEventLoop | None

    def __init__(self, config: ProcessConfig, client: DisManagerClient) -> None:
        self._config = config
        self._client = client

        # Internal managers
        self._runner    = ProcessRunner(self)
        self._logger    = ProcessLogger(self)
        self._relay     = ConsoleRelay(self)
        self._plugins   = PluginManager(self)
        self._backups   = BackupManager(self)
        self._loop      = None

        config.resolve_path().mkdir(parents=True, exist_ok=True)

    # --- Internal Behaviour ---

    def _on_raw_line(self, raw_line: str) -> None:
        cleaned = self._logger.record_line(raw_line)
        if cleaned is not None and self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._on_output_line, cleaned)

    def _on_output_line(self, line: str) -> None:
        self._relay.enqueue(line)
        self._emit_plugin_event('on_process_log', line)
        self._client._addons_manager.emit('on_process_log', self, line)

    def _on_process_stop(self) -> None:
        self._emit_plugin_event('on_process_stop')
        self._client._addons_manager.emit('on_process_stop', self)

    def _on_process_exit(self, reason: str | None, crashed: bool) -> None:
        self._logger.close_session()
        self._relay.finish(reason=reason)
        if crashed:
            self._client._addons_manager.emit('on_process_crash', self)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._on_finish_plugins(crashed=crashed))

    async def _on_start_plugins(self) -> None:
        await self._plugins.load_plugins(reload=False)
        await self._plugins.call_plugins('on_process_start')

    async def _on_finish_plugins(self, *, crashed: bool) -> None:
        if crashed:
            await self._plugins.call_plugins('on_process_crash')
        await self._plugins.unload_plugins()

    def _emit_plugin_event(self, event_name: str, *args: object) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._plugins.call_plugins(event_name, *args))

    # --- Internal API ---

    def _update_config(self, config: ProcessConfig) -> None:
        """Update process configuration in-place."""
        self._config = config

    async def _delete_folder(self) -> None:
        """Safely delete the process working directory if it resides under the workspace root."""
        root = Path.cwd().resolve()
        candidate_dir = self._config.resolve_path().resolve()
        if candidate_dir == root or not candidate_dir.is_relative_to(root):
            return
        if candidate_dir.exists():
            await asyncio.to_thread(shutil.rmtree, candidate_dir)

    async def _send_logs(self) -> None:
        """Send this process's recent 8 MB log buffer to its Discord console thread."""
        await self._relay.send_log_file(self._logger.recent_bytes())

    async def _shutdown(self) -> None:
        """Stop the subprocess gracefully, force-kill after 60 s, and drain its Discord relay."""
        if self._runner.is_alive:
            self.stop()
            deadline = asyncio.get_running_loop().time() + 60.0
            while self._runner.is_alive and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.2)
            if self._runner.is_alive:
                self.kill()
        await self._relay.shutdown()
        await self._plugins.unload_plugins()

    # --- Public API ---

    # Properties

    @property
    def name(self) -> str:
        """Return the configured name of this process."""
        return self._config.name

    @property
    def client(self) -> DisManagerClient:
        """Return the Discord client managing this process."""
        return self._client

    @property
    def path(self) -> Path:
        """Return the resolved working directory for this process."""
        return self._config.resolve_path()

    @property
    def console_thread(self) -> discord.Thread | None:
        """Return the resolved Discord console thread for this process, if available."""
        return self._relay.thread

    @property
    def backups_dir(self) -> Path:
        """Return the resolved ``.backups/<name>`` directory for this process."""
        return self._backups.backups_dir

    @property
    def plugins_dir(self) -> Path:
        """Return the per-process plugins directory."""
        return self._plugins.plugins_dir

    # Lifecycle

    def is_running(self) -> bool:
        """Return ``True`` while the subprocess is alive or its Discord relay is still draining."""
        return self._runner.is_alive or self._relay.is_active

    def start(self) -> bool:
        """Start the configured subprocess and begin reading its output."""
        if self.is_running():
            return False

        self._logger.start_session()
        self._relay.start()
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        try:
            loop = self._runner.start()
        except Exception:
            self._logger.close_session()
            self._relay.finish()
            raise

        if loop is not None:
            loop.create_task(self._on_start_plugins())
        self._client._addons_manager.emit('on_process_start', self)
        return True

    def stop(self) -> bool:
        """Request a graceful stop via ``stop_command``, or fall back to ``kill()``."""
        return self._runner.stop()

    def kill(self) -> bool:
        """Forcefully terminate the process and all of its child processes."""
        return self._runner.kill()

    async def restart(self) -> bool:
        """Stop the process cleanly, wait for exit and relay drain, and start it again."""
        if self.is_running():
            if self._runner.is_alive:
                self.stop()
                deadline = asyncio.get_running_loop().time() + 30.0
                while self._runner.is_alive and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.1)
                if self._runner.is_alive:
                    self.kill()
                    await asyncio.sleep(0.2)
            await self._relay.shutdown()

        return self.start()

    def execute(self, command: str) -> bool:
        """Write a command line to the subprocess stdin."""
        return self._runner.execute(command)

    # Plugins

    async def reload_plugins(self) -> int:
        """Reload per-process plugins when this process is running."""
        if not self.is_running():
            return 0
        return await self._plugins.load_plugins(reload=True)

    async def call_plugins(self, event_name: str, *args: object) -> None:
        """Dispatch a custom or lifecycle event to active plugins of this process."""
        await self._plugins.call_plugins(event_name, *args)

    # Console & Logs

    def add_log(self, log: str) -> None:
        """Enqueue a log line into this process's Discord console relay."""
        self._relay.enqueue(log)

    def last_logs(self, *, limit: int = 40) -> list[str]:
        """Return up to the last ``limit`` log lines from the recent 8 MB buffer."""
        return self._logger.last_lines(limit=limit)

    async def send_to_console(self, message: str) -> discord.Message | None:
        """Send a message directly to this process's Discord console thread."""
        thread = await self._relay.ensure_thread()
        if thread is None:
            return None
        return await thread.send(message)

    # Metrics

    def ram_usage_bytes(self) -> int:
        """Return total RSS memory in bytes for the process tree."""
        return self._runner.ram_usage_bytes()

    def disk_usage_bytes(self) -> int:
        """Return total disk usage in bytes of this process's working directory."""
        return dir_size_bytes(self._config.resolve_path())

    # Backups

    def list_backups(self) -> list[BackupEntry]:
        """Return existing numbered backups for this process, ordered 1..N."""
        return self._backups.list_backups()

    def make_backup(
        self,
        on_progress: Callable[[int, int], None] | None = None,
        *,
        force: bool = False,
    ) -> Path:
        """Create a rotating backup of this process's directory."""
        if not force and self.is_running():
            raise RuntimeError(f"Process '{self.name}' is currently running.")
        return self._backups.make(on_progress)

    def restore_backup(
        self,
        backup: BackupEntry,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Restore ``backup`` into this process's directory."""
        if self.is_running():
            raise RuntimeError(f"Process '{self.name}' is currently running.")
        self._backups.restore(backup.path, on_progress)

