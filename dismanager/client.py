from __future__ import annotations

import discord
from discord.ext import commands

from .config import DisManagerConfig
from .i18n import Translator


class DisManagerClient(commands.Bot):
    """Discord bot client for DisManager."""

    def __init__(self, config: DisManagerConfig, translator: Translator) -> None:
        super().__init__(command_prefix=config.bot_prefix, intents=discord.Intents.all())
        self.config = config
        self._ = translator
        self.panel: discord.TextChannel | None = None
        self._ready_once = False

    async def on_ready(self) -> None:
        if self._ready_once:
            return

        panel = self._resolve_panel()
        if panel is None:
            await self.close()
            return

        self.panel = panel
        self._ready_once = True
        print(self._('Logged in as {}!').format(self.user))

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
