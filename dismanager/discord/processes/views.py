from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from ...core.processes import MAX_PROCESSES, ProcessConfig
from .embed import build_processes_embed
from .modals import DeleteProcessModal, ProcessFormModal

if TYPE_CHECKING:
    from ..client import DisManagerClient


class ProcessesConfigView(discord.ui.View):
    """Interactive view to list, create, edit, and delete persisted processes."""

    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.render()

    def render(self) -> discord.Embed:
        """Rebuild controls from the client's process list and return the embed."""
        self.clear_items()
        processes = self.bot.processes_config

        if processes:
            self.add_item(_ProcessSelect(self.bot, processes))

        self.add_item(_NewProcessButton(self.bot, disabled=len(processes) >= MAX_PROCESSES))
        self.add_item(_DeleteProcessButton(self.bot, disabled=not processes))

        return build_processes_embed(processes, self.bot._)

    async def refresh(self, interaction: discord.Interaction[Any]) -> None:
        """Re-render the view and update the ephemeral Processes message."""
        embed = self.render()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
            return

        message = interaction.message
        if message is not None:
            await interaction.followup.edit_message(message_id=message.id, embed=embed, view=self)


# =========================================
#            Internal Helpers
# =========================================


class _ProcessSelect(discord.ui.Select[ProcessesConfigView]):
    def __init__(self, bot: DisManagerClient, processes: list[ProcessConfig]) -> None:
        options = [
            discord.SelectOption(label=proc.name[:100], value=proc.name)
            for proc in processes[:MAX_PROCESSES]
        ]
        super().__init__(placeholder=bot._('Select a process'), options=options, row=0)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        existing = self.view.bot.get_process_config(self.values[0])
        if existing is None:
            await self.view.refresh(interaction)
            return

        await interaction.response.send_modal(ProcessFormModal(self.view, existing=existing))


class _NewProcessButton(discord.ui.Button[ProcessesConfigView]):
    def __init__(self, bot: DisManagerClient, *, disabled: bool) -> None:
        super().__init__(label=bot._('New'), style=discord.ButtonStyle.green, row=1, disabled=disabled)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.send_modal(ProcessFormModal(self.view))


class _DeleteProcessButton(discord.ui.Button[ProcessesConfigView]):
    def __init__(self, bot: DisManagerClient, *, disabled: bool) -> None:
        super().__init__(label=bot._('Delete'), style=discord.ButtonStyle.red, row=1, disabled=disabled)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        processes = self.view.bot.processes_config
        if not processes:
            await self.view.refresh(interaction)
            return

        await interaction.response.send_modal(
            DeleteProcessModal(self.view, processes, source_message=interaction.message)
        )
