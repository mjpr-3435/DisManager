from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from ..guide import build_guide_embed
from ..utils import confirmation_request

if TYPE_CHECKING:
    from ..client import DisManagerClient


class PanelView(discord.ui.View):
    """Main interactive button bar attached to the DisManager panel."""

    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(_GuideButton())
        self.add_item(_RestartButton(bot))


# =========================================
#            Internal Helpers
# =========================================


class _GuideButton(discord.ui.Button[PanelView]):
    def __init__(self) -> None:
        super().__init__(label='Guide', style=discord.ButtonStyle.gray)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.send_message(embed=build_guide_embed(), ephemeral=True)


class _RestartButton(discord.ui.Button[PanelView]):
    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(label='Restart', style=discord.ButtonStyle.red)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
            await confirm_interaction.response.edit_message(
                content=self.bot._('Restarting...'),
                embed=None,
                view=None,
            )
            await self.bot.request_restart()

        await confirmation_request(
            self.bot._('Are you sure you want to restart DisManager?'),
            interaction=interaction,
            on_confirmation=on_confirmation,
        )
