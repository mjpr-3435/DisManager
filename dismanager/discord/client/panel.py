from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import aiohttp
import discord

from ..panel import PanelView, update_panel
from ..utils import get_or_create_thread

if TYPE_CHECKING:
    from .client import DisManagerClient

_PANEL_REFRESH_SECONDS = 15
_ERROR_THREAD_NAME = 'Error Reports'


class PanelManager:
    """Manages the Discord panel channel, refresh loop, Error Reports thread, and offline state."""

    channel     : discord.TextChannel | None
    error_thread: discord.Thread | None
    _message    : discord.Message | None
    _task       : asyncio.Task[None] | None

    def __init__(self, client: DisManagerClient) -> None:
        self._client        = client
        self.channel        = None
        self.error_thread   = None
        self._message       = None
        self._task          = None
        self._refresh_event = asyncio.Event()

    # --- Internal Behaviour ---

    def _resolve_channel(self) -> discord.TextChannel | None:
        panel_id = self._client._config.panel_id
        channel = self._client.get_channel(panel_id)

        if channel is None:
            print(self._client._('Error: Channel with id {} not found.').format(panel_id))
            return None

        if not isinstance(channel, discord.TextChannel):
            print(self._client._('Error: The panel channel must be a text channel.'))
            return None

        return channel

    async def _loop(self) -> None:
        include_view = True
        while not self._client.is_closed():
            self._refresh_event.clear()
            if self.channel is not None and self._client.user is not None:
                try:
                    view = PanelView(self._client) if include_view else None
                    self._message = await update_panel(
                        self.channel,
                        self._client.user.id,
                        self._client._config.bot_prefix,
                        self._client._,
                        error_thread=self.error_thread,
                        processes=list(self._client.processes),
                        view=view,
                    )
                    include_view = False
                except (aiohttp.ClientError, discord.HTTPException):
                    with contextlib.suppress(Exception):
                        fetched = await self._client.fetch_channel(self.channel.id)
                        if isinstance(fetched, discord.TextChannel):
                            self.channel = fetched
                except Exception:
                    await self._client.report_error('Panel')

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._refresh_event.wait(), timeout=_PANEL_REFRESH_SECONDS)

    async def _mark_offline(self) -> None:
        message = self._message
        if message is None and self.channel is not None and self._client.user is not None:
            with contextlib.suppress(Exception):
                async for candidate in self.channel.history(limit=1, oldest_first=True):
                    if candidate.author.id == self._client.user.id:
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
            self._client._logger.warning('Failed to mark panel offline: %s', exc)

    # --- Internal API ---

    async def ensure_error_thread(self) -> discord.Thread | None:
        """Return the Error Reports thread, creating it if needed."""
        if self.error_thread is None and self.channel is not None:
            with contextlib.suppress(Exception):
                self.error_thread = await get_or_create_thread(self.channel, _ERROR_THREAD_NAME)
        return self.error_thread
    
    async def validate_channel(self) -> bool:
        """Validate the configured panel channel and initialize its Error Reports thread."""
        channel = self._resolve_channel()
        if channel is None:
            return False
        self.channel = channel
        self.error_thread = await get_or_create_thread(channel, _ERROR_THREAD_NAME)
        return True

    def start(self) -> None:
        """Start the background panel refresh loop."""
        self._task = asyncio.create_task(self._loop())

    def refresh(self) -> None:
        """Trigger an immediate panel refresh."""
        self._refresh_event.set()

    async def close(self) -> None:
        """Cancel the panel loop and mark the panel message offline."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._mark_offline()