from __future__ import annotations

import asyncio
import contextlib
import logging
from importlib.metadata import version
from typing import TYPE_CHECKING

import aiohttp
import discord

from ....core.bootstrap.i18n import _
from ...panel import PanelView, update_panel
from ...utils import get_or_create_thread

if TYPE_CHECKING:
    from ..client import DisManagerClient

_PANEL_REFRESH_SECONDS = 15
_ERROR_THREAD_NAME = 'Error Reports'
_FOOTER_ICON_URL = (
    'https://raw.githubusercontent.com/mjpr-3435/DisManager/master/assets/branding/dismanager-icon-512.png'
)
_logger = logging.getLogger(__name__)


class PanelManager:
    """Manages the Discord panel channel, refresh loop, Error Reports thread, and offline state."""

    _channel     : discord.TextChannel | None
    _error_thread: discord.Thread | None
    _message     : discord.Message | None
    _task        : asyncio.Task[None] | None

    def __init__(self, client: DisManagerClient) -> None:
        self._client        = client
        self._channel       = None
        self._error_thread  = None
        self._message       = None
        self._task          = None
        self._refresh_event = asyncio.Event()

    # --- Internal Behaviour ---

    def _resolve_channel(self) -> discord.TextChannel | None:
        panel_id = self._client._config.panel_id
        channel = self._client.get_channel(panel_id)

        if channel is None:
            print(_('Error: Channel with id {} not found.').format(panel_id))
            return None

        if not isinstance(channel, discord.TextChannel):
            print(_('Error: The panel channel must be a text channel.'))
            return None

        return channel

    async def _loop(self) -> None:
        assert self._channel is not None
        include_view = True
        while not self._client.is_closed():
            self._refresh_event.clear()
            try:
                view = PanelView(self._client) if include_view else None
                self._message = await update_panel(self._client, view=view)
                include_view = False
            except (aiohttp.ClientError, discord.HTTPException):
                with contextlib.suppress(Exception):
                    fetched = await self._client.fetch_channel(self._channel.id)
                    if isinstance(fetched, discord.TextChannel):
                        self._channel = fetched
            except Exception:
                await self._client.report_error('Panel')

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._refresh_event.wait(), timeout=_PANEL_REFRESH_SECONDS)

    async def _mark_offline(self) -> None:
        if self._message is None or not self._message.embeds:
            return

        embed = self._message.embeds[0].copy()
        embed.set_footer(text=f"🔴 DisManager v{version('dismanager')}", icon_url=_FOOTER_ICON_URL)
        try:
            await self._message.edit(embed=embed)
        except Exception as exc:
            _logger.warning('Failed to mark panel offline: %s', exc)

    # --- Internal API ---

    @property
    def channel(self) -> discord.TextChannel | None:
        """Return the resolved Discord panel channel, if available."""
        return self._channel

    @property
    def error_thread(self) -> discord.Thread | None:
        """Return the Error Reports thread, if initialized."""
        return self._error_thread

    async def ensure_error_thread(self) -> discord.Thread | None:
        """Return the Error Reports thread, creating it if needed."""
        if self._error_thread is None and self._channel is not None:
            with contextlib.suppress(Exception):
                self._error_thread = await get_or_create_thread(self._channel, _ERROR_THREAD_NAME)
        return self._error_thread

    async def validate_channel(self) -> bool:
        """Validate the configured panel channel and initialize its Error Reports thread."""
        channel = self._resolve_channel()
        if channel is None:
            return False
        self._channel = channel
        self._error_thread = await get_or_create_thread(channel, _ERROR_THREAD_NAME)
        return True

    def refresh(self) -> None:
        """Trigger an immediate panel refresh."""
        self._refresh_event.set()

    def start(self) -> None:
        """Start the background panel refresh loop."""
        self._task = asyncio.create_task(self._loop())

    async def close(self) -> None:
        """Cancel the panel loop and mark the panel message offline."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._mark_offline()