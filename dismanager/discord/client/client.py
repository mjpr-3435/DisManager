from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Literal

import discord
from discord.ext import commands

from ...core.bootstrap.config import DisManagerConfig
from ...core.bootstrap.i18n import _
from ...core.bootstrap.logs import LogSession
from ...core.processes import ManagedProcess, ProcessConfig, ProcessDeleteRequest
from .commands import setup as setup_commands
from .events import setup as setup_events
from .managers import AddonManager, ConsoleManager, PanelManager, ProcessManager

_ERROR_NOTICE_COOLDOWN_SECONDS = 60.0


class DisManagerClient(commands.Bot):
    """Discord bot client for DisManager."""

    _error_notice_timestamps: dict[str, float]

    def __init__(self, config: DisManagerConfig, log_session: LogSession) -> None:
        super().__init__(command_prefix=config.bot_prefix, intents=discord.Intents.all())
        # Core services
        self._config                 = config
        self._log_session            = log_session
        self._logger                 = logging.getLogger(__name__)

        # Lifecycle state
        self._ready_once             = False
        self._closing                = False
        self._should_restart         = False
        # Cooldown map {context: monotonic_timestamp} to avoid spamming Error Reports (60s per source)
        self._error_notice_timestamps = {}

        # Internal managers
        self._panel_manager          = PanelManager(self)
        self._console_manager        = ConsoleManager(self)
        self._addons_manager         = AddonManager(self)
        self._processes_manager      = ProcessManager(self)

    # --- Discord Hooks ---

    async def setup_hook(self) -> None:
        await setup_commands(self)
        await setup_events(self)

    async def on_ready(self) -> None:
        if self._ready_once:
            return

        if not await self._panel_manager.validate_channel():
            await self.close()
            return

        self._ready_once = True
        self._processes_manager.load()
        print(_('Logged in as {}!').format(self.user))
        await self._addons_manager.load_addons(reload=False)
        self._log_session.mute_console()

        self._panel_manager.start()
        self._console_manager.start()

    # --- Internal Behaviour ---

    def _refresh_panel(self) -> None:
        """Signal the panel loop to refresh immediately."""
        self._panel_manager.refresh()

    def _emit_addon_event(self, event_name: str, *args: object) -> None:
        """Schedule an addon event dispatch on the active event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._addons_manager.call_addons(event_name, *args))

    def _on_processes_edit(
        self,
        event: Literal['new', 'update', 'delete'],
        payload: ProcessConfig | ProcessDeleteRequest,
    ) -> None:
        """Persist process changes, update client state, and handle folder side effects."""
        self._processes_manager.on_edit(event, payload)

    # --- Public API ---
    
    @property
    def processes(self) -> tuple[ManagedProcess, ...]:
        """Return a read-only snapshot of all managed processes."""
        return tuple(self._processes_manager.list_processes())
    
    def find_process(self, name: str) -> ManagedProcess | None:
        """Return a managed process matching ``name`` case-insensitively."""
        return self._processes_manager.find(name)

    def restart_requested(self) -> bool:
        """Return whether the client closed due to a restart request."""
        return self._should_restart

    async def close(self) -> None:
        """Shut down background tasks and close the Discord connection."""
        if self._closing:
            return
        self._closing = True

        if self._ready_once:
            print(_('Closing DisManager...'))

        self._console_manager.stop()
        await self._processes_manager.shutdown_all()
        await self._addons_manager.unload_addons()
        await self._panel_manager.close()
        await super().close()

    async def request_restart(self) -> None:
        """Shut down via the unified close flow and signal the runner to relaunch."""
        self._should_restart = True
        await self.close()

    async def reload_addons(self) -> int:
        """Unload, purge cached addon modules, and reload all addons."""
        return await self._addons_manager.load_addons(reload=True)

    async def report_error(self, context: str) -> None:
        """Log the active exception traceback to file and send a rate-limited notice to Error Reports."""
        self._logger.exception('%s', context)

        now = time.monotonic()
        last_sent = self._error_notice_timestamps.get(context, 0.0)
        if now - last_sent < _ERROR_NOTICE_COOLDOWN_SECONDS:
            return
        self._error_notice_timestamps[context] = now

        error_thread = await self._panel_manager.ensure_error_thread()
        if error_thread is not None:
            notice = _('Unexpected error. Use `{}log` to inspect the log.').format(
                self._config.bot_prefix
            )
            with contextlib.suppress(Exception):
                await error_thread.send(f'⚠ **[{context}]** {notice}')
