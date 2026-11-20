from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from ...core.bootstrap.i18n import _
from ..utils import confirmation_request
from .backups import BackupsView
from .files import FilesView
from .guide import GuideView
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
        self.add_item(_GuideButton(bot))
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
    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(label='Guide', style=discord.ButtonStyle.gray)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        view = GuideView(self.bot)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)


class _RestartButton(discord.ui.Button[PanelView]):
    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(label='Restart', style=discord.ButtonStyle.red)
        self.bot = bot

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
            await confirm_interaction.response.edit_message(
                content=_('Checking if there are open processes...'),
                embed=None,
                view=None,
            )

            async def _update_status(text: str) -> None:
                await confirm_interaction.edit_original_response(content=text)

            async def _cleanup_status() -> None:
                await confirm_interaction.delete_original_response()

            user = confirm_interaction.user
            await self.bot.request_restart(
                requested_by=f'Discord panel ({user} id={user.id})',
                on_progress=_update_status,
                on_before_close=_cleanup_status,
            )

        await confirmation_request(
            _('Are you sure you want to restart DisManager?'),
            interaction=interaction,
            on_confirmation=on_confirmation,
        )
