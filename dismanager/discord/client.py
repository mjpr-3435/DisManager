from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from pathlib import Path
from typing import Literal

import aiohttp
import discord
from discord.ext import commands

from ..addons import AddonManager
from ..core.config import DisManagerConfig
from ..core.console import build_console_handler, console_loop
from ..core.i18n import Translator
from ..core.logs import mute_console_logging
from ..core.processes import (
    ProcessConfig,
    ProcessConfigError,
    ProcessDeleteRequest,
    delete_process,
    load_processes,
    upsert_process,
)
from ..processes import ManagedProcess
from .commands import setup as setup_commands
from .panel import PanelView, update_panel
from .utils import get_or_create_thread

_PANEL_REFRESH_SECONDS = 15
_ERROR_THREAD_NAME = 'Error Reports'
_ERROR_NOTICE_COOLDOWN_SECONDS = 60.0


class DisManagerClient(commands.Bot):
    """Discord bot client for DisManager."""

    def __init__(self, config: DisManagerConfig, translator: Translator) -> None:
        super().__init__(command_prefix=config.bot_prefix, intents=discord.Intents.all())
        self._config = config
        self._ = translator
        self._logger = logging.getLogger(__name__)
        self.processes_config: list[ProcessConfig] = load_processes()
        self._processes: dict[str, ManagedProcess] = {
            proc.name: ManagedProcess(proc, self) for proc in self.processes_config
        }
        self.panel: discord.TextChannel | None = None
        self._panel_message: discord.Message | None = None
        self.error_thread: discord.Thread | None = None
        self._ready_once = False
        self._closing = False
        self.should_restart = False
        self._panel_task: asyncio.Task[None] | None = None
        self._panel_refresh_event = asyncio.Event()
        self._console_task: asyncio.Task[None] | None = None
        self._last_error_notice: dict[str, float] = {}
        self.addons = AddonManager(self)

    # --- Discord Hooks ---

    async def setup_hook(self) -> None:
        await setup_commands(self)

    async def on_ready(self) -> None:
        if self._ready_once:
            return

        panel = self._resolve_panel()
        if panel is None:
            await self.close()
            return

        self.panel = panel
        self.error_thread = await get_or_create_thread(panel, _ERROR_THREAD_NAME)
        for proc in self.processes_config:
            await get_or_create_thread(panel, f'Console {proc.name}')
        self._ready_once = True
        print(self._('Logged in as {}!').format(self.user))
        await self.addons.load_addons(reload=False)
        mute_console_logging()

        header = (
            f"{self._('Commands')}: "
            'start, stop, restart, kill, plreload, adreload, status, exit'
        )
        handler = build_console_handler(self._, self.close, self.reload_addons)
        self._panel_task = asyncio.create_task(self._panel_loop())
        self._console_task = asyncio.create_task(console_loop(handler, header=header))

    async def on_thread_update(self, _before: discord.Thread, after: discord.Thread) -> None:
        if self.panel is None or after.parent_id != self.panel.id or not after.archived:
            return
        if after.name == _ERROR_THREAD_NAME or after.name.removeprefix('Console ') in self._processes:
            with contextlib.suppress(discord.HTTPException):
                await after.edit(archived=False)
            self._panel_refresh_event.set()

    async def on_message(self, message: discord.Message) -> None:
        await self.process_commands(message)
        if message.author.bot or self.panel is None:
            return

        if (
            not isinstance(message.channel, discord.Thread)
            or message.channel.parent_id != self.panel.id
            or not message.channel.name.startswith('Console ')
        ):
            return

        target_name = message.channel.name.removeprefix('Console ').strip()
        process = self._processes.get(target_name)
        if process is None:
            return

        cmd = message.content.strip().lower()
        if cmd == 'start':
            try:
                process.start()
            except ProcessConfigError as exc:
                await message.channel.send(f'✖ {exc}')
        elif cmd == 'stop':
            process.stop()
        elif cmd == 'kill':
            process.kill()
        elif cmd == 'restart':
            asyncio.create_task(process.restart())
        elif cmd == 'logs':
            await process.send_logs()
        else:
            process.execute(message.content)

    # --- Internal Helpers ---

    def _resolve_panel(self) -> discord.TextChannel | None:
        panel_id = self._config.panel_id
        channel = self.get_channel(panel_id)

        if channel is None:
            print(self._('Error: Channel with id {} not found.').format(panel_id))
            return None

        if not isinstance(channel, discord.TextChannel):
            print(self._('Error: The panel channel must be a text channel.'))
            return None

        return channel

    async def _panel_loop(self) -> None:
        include_view = True
        while not self.is_closed():
            self._panel_refresh_event.clear()
            if self.panel is not None and self.user is not None:
                try:
                    view = PanelView(self) if include_view else None
                    self._panel_message = await update_panel(
                        self.panel,
                        self.user.id,
                        self._config.bot_prefix,
                        self._,
                        error_thread=self.error_thread,
                        processes=list(self._processes.values()),
                        view=view,
                    )
                    include_view = False
                except (aiohttp.ClientError, discord.HTTPException):
                    with contextlib.suppress(Exception):
                        fetched = await self.fetch_channel(self.panel.id)
                        if isinstance(fetched, discord.TextChannel):
                            self.panel = fetched
                except Exception:
                    await self.report_error('Panel')

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._panel_refresh_event.wait(), timeout=_PANEL_REFRESH_SECONDS)

    # --- Public API ---

    async def close(self) -> None:
        """Shut down background tasks and close the Discord connection."""
        if self._closing:
            return
        self._closing = True

        if self._ready_once:
            print(self._('Closing DisManager...'))

        current = asyncio.current_task()
        if self._console_task is not None and self._console_task is not current and not self._console_task.done():
            self._console_task.cancel()

        if self._panel_task is not None and self._panel_task is not current and not self._panel_task.done():
            self._panel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._panel_task

        if self._processes:
            if any(proc.is_running() for proc in self._processes.values()):
                print(self._('Closing processes...'))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*(proc.shutdown() for proc in self._processes.values()), return_exceptions=True),
                    timeout=65.0,
                )

        await self.addons.unload_addons()
        await self._mark_panel_offline()
        await super().close()

    async def _mark_panel_offline(self) -> None:
        message = self._panel_message
        if message is None and self.panel is not None and self.user is not None:
            with contextlib.suppress(Exception):
                async for candidate in self.panel.history(limit=1, oldest_first=True):
                    if candidate.author.id == self.user.id:
                        message = candidate
                    break

        if message is None or not message.embeds:
            return

        embed = message.embeds[0].copy()
        footer_text = embed.footer.text or 'DisManager'
        embed.set_footer(text=f"🔴 {footer_text.removeprefix('🟢 ')}")
        try:
            await message.edit(embed=embed)
        except Exception as exc:
            self._logger.warning('Failed to mark panel offline: %s', exc)

    async def request_restart(self) -> None:
        """Shut down via the unified close flow and signal the runner to relaunch."""
        self.should_restart = True
        await self.close()

    async def report_error(self, context: str) -> None:
        """Log the active exception traceback to file and send a rate-limited notice to Error Reports."""
        self._logger.exception('%s', context)

        now = time.monotonic()
        last_sent = self._last_error_notice.get(context, 0.0)
        if now - last_sent < _ERROR_NOTICE_COOLDOWN_SECONDS:
            return
        self._last_error_notice[context] = now

        if self.error_thread is None and self.panel is not None:
            with contextlib.suppress(Exception):
                self.error_thread = await get_or_create_thread(self.panel, _ERROR_THREAD_NAME)

        if self.error_thread is not None:
            notice = self._('Unexpected error. Use `{}log` to inspect the log.').format(
                self._config.bot_prefix
            )
            with contextlib.suppress(Exception):
                await self.error_thread.send(f'⚠ **[{context}]** {notice}')

    async def _ensure_console_thread(self, name: str) -> None:
        if self.panel is not None:
            with contextlib.suppress(Exception):
                await get_or_create_thread(self.panel, f'Console {name}')
        self._panel_refresh_event.set()

    async def reload_addons(self) -> int:
        """Unload, purge cached addon modules, and reload all addons."""
        return await self.addons.load_addons(reload=True)

    def emit_addon_event(self, event_name: str, *args: object) -> None:
        """Schedule an addon event dispatch on the active event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.addons.call_addons(event_name, *args))

    def get_process_config(self, name: str) -> ProcessConfig | None:
        """Return a configured process from the client's in-memory state."""
        return next((proc for proc in self.processes_config if proc.name == name), None)

    def find_process(self, name: str) -> ManagedProcess | None:
        """Return a managed process matching ``name`` case-insensitively."""
        target = name.strip().lower()
        return next((proc for key, proc in self._processes.items() if key.lower() == target), None)

    def on_processes_edit(
        self,
        event: Literal['new', 'update', 'delete'],
        payload: ProcessConfig | ProcessDeleteRequest,
    ) -> None:
        """Persist process changes, update client state, and handle folder side effects."""
        if event == 'new':
            assert isinstance(payload, ProcessConfig)
            self.processes_config = upsert_process(payload, is_edit=False)
            self._processes[payload.name] = ManagedProcess(payload, self)
            try:
                payload.resolve_path().mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ProcessConfigError(f"Could not create process folder '{payload.name}': {exc}") from exc
            if self.panel is not None:
                asyncio.create_task(self._ensure_console_thread(payload.name))
            else:
                self._panel_refresh_event.set()
            return

        if event == 'update':
            assert isinstance(payload, ProcessConfig)
            self.processes_config = upsert_process(payload, is_edit=True)
            process = self._processes.get(payload.name)
            if process is not None:
                process.update_config(payload)
            self._panel_refresh_event.set()
            return

        if event == 'delete':
            assert isinstance(payload, ProcessDeleteRequest)
            target_proc = self.get_process_config(payload.name)
            self.processes_config = delete_process(payload.name)
            process = self._processes.pop(payload.name, None)
            target_dir: Path | None = None
            if payload.delete_files and target_proc is not None:
                root = Path.cwd().resolve()
                candidate_dir = target_proc.resolve_path().resolve()
                if candidate_dir != root and candidate_dir.is_relative_to(root):
                    target_dir = candidate_dir
            if process is not None or target_dir is not None:
                asyncio.create_task(self._cleanup_deleted_process(process, target_dir))
            self._panel_refresh_event.set()
            return

        raise ValueError(f'Unsupported process edit event: {event}')

    async def _cleanup_deleted_process(
        self,
        process: ManagedProcess | None,
        target_dir: Path | None,
    ) -> None:
        if process is not None:
            await process.shutdown()
        if target_dir is not None and target_dir.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, target_dir)
            except OSError:
                await self.report_error(f'DeleteProcess:{target_dir.name}')
