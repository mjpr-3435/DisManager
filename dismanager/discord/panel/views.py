from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from ...core.bootstrap.i18n import _
from ..utils import confirmation_request
from .backups import BackupsView
from .files import FilesView
from .guide import build_guide_embed
from .processes import ProcessesConfigView

if TYPE_CHECKING:
    from ..client import DisManagerClient


class PanelView(discord.ui.View):
    """Main interactive button bar attached to the DisManager panel."""

    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(_ConfigButton(bot))
        self.add_item(_BackupsButton(bot))
        self.add_item(_FilesButton(bot))
        self.add_item(_GuideButton())
        self.add_item(_RestartButton(bot))


# =========================================
#            Internal Helpers
# =========================================


class _FilesButton(discord.ui.Button[PanelView]):
    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(label='Files', style=discord.ButtonStyle.gray)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        view = FilesView(self.bot)
        embed = view.render(view.path)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class _ConfigButton(discord.ui.Button[PanelView]):
    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(label='Config', style=discord.ButtonStyle.gray)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        view = ProcessesConfigView(self.bot)
        embed = view.render()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class _BackupsButton(discord.ui.Button[PanelView]):
    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(label='Backups', style=discord.ButtonStyle.gray)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        view = BackupsView(self.bot)
        embed = view.build_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


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
                content=_('Restarting...'),
                embed=None,
                view=None,
            )
            await confirm_interaction.delete_original_response()
            await self.bot.request_restart()

        await confirmation_request(
            _('Are you sure you want to restart DisManager?'),
            interaction=interaction,
            on_confirmation=on_confirmation,
        )
