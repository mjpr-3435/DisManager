from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from ...core.processes import MAX_PROCESSES, ProcessConfig, ProcessConfigError, get_process, load_processes
from .embed import build_processes_embed
from .modals import DeleteProcessModal, ProcessFormModal

if TYPE_CHECKING:
    from ..client import DisManagerClient


class ProcessesConfigView(discord.ui.View):
    """Interactive view to list, create, edit, and delete persisted processes."""

    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self._processes: list[ProcessConfig] = []
        self.render()

    def render(self) -> discord.Embed:
        """Reload persisted processes, rebuild controls, and return the embed."""
        self.clear_items()
        error_text: str | None = None
        try:
            self._processes = load_processes()
        except ProcessConfigError as exc:
            self._processes = []
            error_text = f'✖ {exc}'

        if self._processes:
            self.add_item(_ProcessSelect(self.bot, self._processes))

        self.add_item(_NewProcessButton(self.bot, disabled=len(self._processes) >= MAX_PROCESSES))
        self.add_item(_DeleteProcessButton(self.bot, disabled=not self._processes))

        embed = build_processes_embed(self._processes, self.bot._)
        if error_text is not None:
            embed.description = f'```\n{error_text}```'
        return embed

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
        existing = get_process(self.values[0])
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
        processes = load_processes()
        if not processes:
            await self.view.refresh(interaction)
            return

        await interaction.response.send_modal(
            DeleteProcessModal(self.view, processes, source_message=interaction.message)
        )
