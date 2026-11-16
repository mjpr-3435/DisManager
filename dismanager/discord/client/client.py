from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Literal

import aiohttp
import discord
from discord.ext import commands

from ...core.config import DisManagerConfig
from ...core.i18n import Translator
from ...core.logs import LogSession
from ...core.processes import ManagedProcess, ProcessConfig, ProcessConfigError, ProcessDeleteRequest
from ..panel import PanelView, update_panel
from ..utils import get_or_create_thread
from .addons import AddonManager
from .commands import setup as setup_commands
from .console import ConsoleManager
from .processes import ProcessManager

_PANEL_REFRESH_SECONDS = 15
_ERROR_THREAD_NAME = 'Error Reports'
_ERROR_NOTICE_COOLDOWN_SECONDS = 60.0


class DisManagerClient(commands.Bot):
    """Discord bot client for DisManager."""

    def __init__(
        self,
        config: DisManagerConfig,
        translator: Translator,
        log_session: LogSession,
    ) -> None:
        super().__init__(command_prefix=config.bot_prefix, intents=discord.Intents.all())
        self._config = config
        self._ = translator
        self._log_session = log_session
        self._logger = logging.getLogger(__name__)
        self.panel: discord.TextChannel | None = None
        self._panel_message: discord.Message | None = None
        self.error_thread: discord.Thread | None = None
        self._ready_once = False
        self._closing = False
        self._should_restart = False
        self._panel_task: asyncio.Task[None] | None = None
        self._panel_refresh_event = asyncio.Event()
        self._last_error_notice: dict[str, float] = {}
        self.addons = AddonManager(self)
        self.processes = ProcessManager(self)
        self._console = ConsoleManager(self)

    @property
    def max_backups(self) -> int:
        return self._config.backups

    @property
    def log_session(self) -> LogSession:
        """Return the active logging session for this execution."""
        return self._log_session

    @property
    def processes_config(self) -> list[ProcessConfig]:
        """Return the configured processes list."""
        return self.processes.configs

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
        for proc in self.processes.configs:
            await get_or_create_thread(panel, f'Console {proc.name}')
        self._ready_once = True
        print(self._('Logged in as {}!').format(self.user))
        await self.addons.load_addons(reload=False)
        self._log_session.mute_console()

        self._panel_task = asyncio.create_task(self._panel_loop())
        self._console.start()

    async def on_thread_update(self, _before: discord.Thread, after: discord.Thread) -> None:
        if self.panel is None or after.parent_id != self.panel.id or not after.archived:
            return
        thread_proc = after.name.removeprefix('Console ')
        if after.name == _ERROR_THREAD_NAME or self.processes.get_config(thread_proc) is not None:
            with contextlib.suppress(discord.HTTPException):
                await after.edit(archived=False)
            self.refresh_panel()

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
        process = self.processes.find(target_name)
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
        elif cmd == 'plreload':
            count = await process.reload_plugins()
            await message.channel.send(self._('✔ Reloaded {} plugin(s).').format(count), delete_after=2)
        else:
            process.execute(message.content)

    # --- Public API ---

    async def close(self) -> None:
        """Shut down background tasks and close the Discord connection."""
        if self._closing:
            return
        self._closing = True

        if self._ready_once:
            print(self._('Closing DisManager...'))

        self._console.stop()

        current = asyncio.current_task()
        if self._panel_task is not None and self._panel_task is not current and not self._panel_task.done():
            self._panel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._panel_task

        await self.processes.shutdown_all()
        await self.addons.unload_addons()
        await self._mark_panel_offline()
        await super().close()

    def restart_requested(self) -> bool:
        """Return whether the client closed due to a restart request."""
        return self._should_restart

    async def request_restart(self) -> None:
        """Shut down via the unified close flow and signal the runner to relaunch."""
        self._should_restart = True
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

    def refresh_panel(self) -> None:
        """Signal the panel loop to refresh immediately."""
        self._panel_refresh_event.set()

    async def ensure_console_thread(self, name: str) -> None:
        """Create the ``Console <name>`` thread if needed and refresh the panel."""
        if self.panel is not None:
            with contextlib.suppress(Exception):
                await get_or_create_thread(self.panel, f'Console {name}')
        self.refresh_panel()

    async def reload_addons(self) -> int:
        """Unload, purge cached addon modules, and reload all addons."""
        return await self.addons.load_addons(reload=True)

    async def reload_plugins(self, process_name: str | None = None) -> int:
        """Reload per-process plugins for ``process_name`` or all active processes."""
        return await self.processes.reload_plugins(process_name)

    def emit_addon_event(self, event_name: str, *args: object) -> None:
        """Schedule an addon event dispatch on the active event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.addons.call_addons(event_name, *args))

    def get_process_config(self, name: str) -> ProcessConfig | None:
        """Return a configured process from in-memory state."""
        return self.processes.get_config(name)

    def find_process(self, name: str) -> ManagedProcess | None:
        """Return a managed process matching ``name`` case-insensitively."""
        return self.processes.find(name)

    def on_processes_edit(
        self,
        event: Literal['new', 'update', 'delete'],
        payload: ProcessConfig | ProcessDeleteRequest,
    ) -> None:
        """Persist process changes, update client state, and handle folder side effects."""
        self.processes.on_edit(event, payload)

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
                        processes=self.processes.list_processes(),
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
