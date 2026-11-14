from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import aiohttp
import discord
from discord.ext import commands

from ..core.config import DisManagerConfig
from ..core.console import build_console_handler, console_loop
from ..core.i18n import Translator
from ..core.logs import mute_console_logging
from .commands import setup as setup_commands
from .panel import PanelView, update_panel
from .threads import get_or_create_thread

PANEL_REFRESH_SECONDS = 15
ERROR_THREAD_NAME = 'Error Reports'
ERROR_NOTICE_COOLDOWN_SECONDS = 60.0


class DisManagerClient(commands.Bot):
    """Discord bot client for DisManager."""

    def __init__(self, config: DisManagerConfig, translator: Translator) -> None:
        super().__init__(command_prefix=config.bot_prefix, intents=discord.Intents.all())
        self.config = config
        self._ = translator
        self.logger = logging.getLogger(__name__)
        self.panel: discord.TextChannel | None = None
        self.error_thread: discord.Thread | None = None
        self._ready_once = False
        self._closing = False
        self.should_restart = False
        self._panel_task: asyncio.Task[None] | None = None
        self._console_task: asyncio.Task[None] | None = None
        self._last_error_notice: dict[str, float] = {}

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
        self.error_thread = await get_or_create_thread(panel, ERROR_THREAD_NAME)
        self._ready_once = True
        print(self._('Logged in as {}!').format(self.user))
        mute_console_logging()

        header = (
            f"{self._('Commands')}: "
            'start, stop, restart, kill, plreload, adreload, status, exit'
        )
        handler = build_console_handler(self._, self.close)
        self._panel_task = asyncio.create_task(self._panel_loop())
        self._console_task = asyncio.create_task(console_loop(handler, header=header))

    # --- Internal Helpers ---

    def _resolve_panel(self) -> discord.TextChannel | None:
        panel_id = self.config.panel_id
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
            if self.panel is not None and self.user is not None:
                try:
                    view = PanelView(self) if include_view else None
                    await update_panel(
                        self.panel,
                        self.user.id,
                        self.config.bot_prefix,
                        self._,
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

            await asyncio.sleep(PANEL_REFRESH_SECONDS)

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

        await super().close()

    async def request_restart(self) -> None:
        """Shut down via the unified close flow and signal the runner to relaunch."""
        self.should_restart = True
        await self.close()

    async def report_error(self, context: str) -> None:
        """Log the active exception traceback to file and send a rate-limited notice to Error Reports."""
        self.logger.exception('%s', context)

        now = time.monotonic()
        last_sent = self._last_error_notice.get(context, 0.0)
        if now - last_sent < ERROR_NOTICE_COOLDOWN_SECONDS:
            return
        self._last_error_notice[context] = now

        if self.error_thread is None and self.panel is not None:
            with contextlib.suppress(Exception):
                self.error_thread = await get_or_create_thread(self.panel, ERROR_THREAD_NAME)

        if self.error_thread is not None:
            notice = self._('Unexpected error. Use `{}log` to inspect the log.').format(
                self.config.bot_prefix
            )
            with contextlib.suppress(Exception):
                await self.error_thread.send(f'⚠ **[{context}]** {notice}')
