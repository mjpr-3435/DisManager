from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import subprocess
import threading
from typing import TYPE_CHECKING, Any

import psutil

from ...process_store import ProcessConfigError

if TYPE_CHECKING:
    from ..process import ManagedProcess


class ProcessRunner:
    """OS subprocess runner and lifecycle coordinator for a ``ManagedProcess``."""

    _process       : subprocess.Popen[bytes] | None
    _reader_thread : threading.Thread | None
    _loop          : asyncio.AbstractEventLoop | None

    def __init__(self, process: ManagedProcess) -> None:
        self._process_obj    = process
        self._process        = None
        self._stop_requested = False
        self._reader_thread  = None
        self._loop           = None

    # --- Internal Behaviour ---

    # Subprocess I/O

    def _read_output(
        self,
        proc: subprocess.Popen[bytes],
        loop: asyncio.AbstractEventLoop | None,
    ) -> None:
        stdout = proc.stdout
        if stdout is not None:
            try:
                for raw_line in iter(stdout.readline, b''):
                    decoded = raw_line.decode('utf-8', errors='replace').rstrip('\r\n')
                    self._on_raw_line(decoded)
            finally:
                with contextlib.suppress(OSError):
                    stdout.close()

        returncode = proc.wait()
        stop_requested = self._stop_requested
        if self._process is proc:
            self._process = None
            self._stop_requested = False

        if loop is not None and not loop.is_closed():
            crashed = not stop_requested and returncode != 0
            reason = f'Process exited unexpectedly (code {returncode}).' if crashed else None
            loop.call_soon_threadsafe(self._on_process_exit, reason, crashed)

    # Lifecycle Hooks

    def _on_raw_line(self, raw_line: str) -> None:
        cleaned = self._process_obj._logger.record_line(raw_line)
        if cleaned is not None and self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._on_output_line, cleaned)

    def _on_output_line(self, line: str) -> None:
        self._process_obj._console_thread.enqueue(line)
        self._emit_plugin_event('on_process_log', line)
        self._process_obj.client._addons_manager.emit('on_process_log', self._process_obj, line)

    def _on_process_stop(self) -> None:
        self._emit_plugin_event('on_process_stop')
        self._process_obj.client._addons_manager.emit('on_process_stop', self._process_obj)

    def _on_process_exit(self, reason: str | None, crashed: bool) -> None:
        self._process_obj._logger.close_session()
        self._process_obj._console_thread.finish(reason=reason)
        if crashed:
            self._process_obj.client._addons_manager.emit('on_process_crash', self._process_obj)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._on_finish_plugins(crashed=crashed))

    async def _on_start_plugins(self) -> None:
        await self._process_obj._plugins.load_plugins(reload=False)
        await self._process_obj._plugins.call_plugins('on_process_start')

    async def _on_finish_plugins(self, *, crashed: bool) -> None:
        if crashed:
            await self._process_obj._plugins.call_plugins('on_process_crash')
        await self._process_obj._plugins.unload_plugins()

    def _emit_plugin_event(self, event_name: str, *args: object) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._process_obj._plugins.call_plugins(event_name, *args))

    # --- Internal API ---

    @property
    def is_alive(self) -> bool:
        """Return ``True`` while the underlying OS subprocess is still running."""
        return self._process is not None and self._process.poll() is None

    def start(self) -> bool:
        """Spawn the configured subprocess, start logging/relay, and notify extensions."""
        if self._process_obj.is_running():
            return False

        config = self._process_obj._config
        raw_cmd = config.start_command.strip()
        if not raw_cmd:
            raise ProcessConfigError(f"Process '{config.name}' has an empty start command.")

        args = (
            shlex.split(raw_cmd, posix=True)
            if os.name != 'nt'
            else [
                token[1:-1]
                if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
                else token
                for token in shlex.split(raw_cmd, posix=False)
            ]
        )
        if not args:
            raise ProcessConfigError(f"Process '{config.name}' has an invalid start command.")

        cwd = config.resolve_path()
        cwd.mkdir(parents=True, exist_ok=True)

        self._stop_requested = False

        popen_kwargs: dict[str, Any] = {
            'cwd': cwd,
            'stdin': subprocess.PIPE,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.STDOUT,
        }
        if os.name == 'nt':
            popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs['start_new_session'] = True

        self._process_obj._logger.start_session()
        self._process_obj._console_thread.start()
        try:
            proc = subprocess.Popen(args, **popen_kwargs)
        except OSError as exc:
            self._process_obj._logger.close_session()
            self._process_obj._console_thread.finish()
            raise ProcessConfigError(f"Could not start '{config.name}': {exc}") from exc

        self._process = proc
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._loop = loop

        self._reader_thread = threading.Thread(
            target=self._read_output,
            args=(proc, loop),
            name=f'process-reader-{config.name}',
            daemon=True,
        )
        self._reader_thread.start()

        if loop is not None:
            loop.create_task(self._on_start_plugins())
        self._process_obj.client._addons_manager.emit('on_process_start', self._process_obj)
        return True

    def stop(self) -> bool:
        """Request a graceful stop via ``stop_command``, or fall back to ``kill()``."""
        if not self.is_alive:
            return False

        stop_command = self._process_obj._config.stop_command
        if not stop_command:
            return self.kill()

        if not self._stop_requested:
            self._stop_requested = True
            self._on_process_stop()
        return self.execute(stop_command)

    def execute(self, command: str) -> bool:
        """Write a command line to the subprocess stdin."""
        proc = self._process
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False

        try:
            proc.stdin.write(f'{command}\n'.encode())
            proc.stdin.flush()
            return True
        except OSError:
            return False

    def kill(self) -> bool:
        """Forcefully terminate the process and all of its child processes."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return False

        if not self._stop_requested:
            self._stop_requested = True
            self._on_process_stop()
        with contextlib.suppress(psutil.Error, OSError):
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.Error, OSError):
                    child.kill()
            parent.kill()

        with contextlib.suppress(OSError):
            proc.kill()
        return True

    def ram_usage_bytes(self) -> int:
        """Return total RSS memory in bytes for the process tree."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return 0

        try:
            parent = psutil.Process(proc.pid)
            total = int(parent.memory_info().rss)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.Error):
                    total += int(child.memory_info().rss)
            return total
        except psutil.Error:
            return 0
