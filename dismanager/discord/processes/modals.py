from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from ...core.processes import ProcessConfig, ProcessConfigError, delete_process, upsert_process, validate_process_data
from ..utils import confirmation_request

if TYPE_CHECKING:
    from .views import ProcessesConfigView


class ProcessFormModal(discord.ui.Modal):
    """Modal form to create or edit a persisted process configuration."""

    def __init__(self, processes_view: ProcessesConfigView, *, existing: ProcessConfig | None = None) -> None:
        bot = processes_view.bot
        title = bot._('New process') if existing is None else f"{bot._('Edit')}: {existing.name}"[:45]
        super().__init__(title=title)
        self._processes_view = processes_view
        self._existing = existing

        self._name_input: discord.ui.TextInput[Any] | None = None
        if existing is None:
            self._name_input = discord.ui.TextInput(
                label=bot._('Name'),
                style=discord.TextStyle.short,
                placeholder='app',
                max_length=64,
            )
            self.add_item(self._name_input)

        self._start_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label=bot._('Start command'),
            style=discord.TextStyle.short,
            placeholder='./start.sh',
            required=False,
            default=existing.start_command if existing is not None else '',
            max_length=512,
        )
        self._stop_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label=bot._('Stop command'),
            style=discord.TextStyle.short,
            placeholder='stop',
            required=False,
            default=existing.stop_command if existing is not None else '',
            max_length=256,
        )
        self._blacklist_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label=bot._('Blacklist'),
            style=discord.TextStyle.paragraph,
            placeholder=bot._('One entry per line'),
            required=False,
            default='\n'.join(existing.blacklist) if existing is not None else '',
            max_length=1000,
        )
        self.add_item(self._start_input)
        self.add_item(self._stop_input)
        self.add_item(self._blacklist_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        name = self._existing.name if self._existing is not None else (
            self._name_input.value if self._name_input is not None else ''
        )
        try:
            config = validate_process_data(
                name=name,
                start_command=self._start_input.value,
                stop_command=self._stop_input.value,
                blacklist=self._blacklist_input.value,
            )
            upsert_process(config, is_edit=self._existing is not None)
        except ProcessConfigError as exc:
            await interaction.response.send_message(f'✖ {exc}', ephemeral=True)
            return

        await self._processes_view.refresh(interaction)


class DeleteProcessModal(discord.ui.Modal):
    """Modal with a process selector to delete a persisted process."""

    def __init__(
        self,
        processes_view: ProcessesConfigView,
        processes: list[ProcessConfig],
        *,
        source_message: discord.Message | None,
    ) -> None:
        bot = processes_view.bot
        super().__init__(title=bot._('Delete a process'))
        self._processes_view = processes_view
        self._source_message = source_message
        self._process_select: discord.ui.Select[Any] = discord.ui.Select(
            options=[discord.SelectOption(label=proc.name[:100], value=proc.name) for proc in processes[:25]]
        )
        self.add_item(discord.ui.Label(text=bot._('Process'), component=self._process_select))

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        target_name = self._process_select.values[0]

        async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
            try:
                delete_process(target_name)
            except ProcessConfigError as exc:
                await confirm_interaction.response.edit_message(content=f'✖ {exc}', embed=None, view=None)
                return

            await confirm_interaction.response.edit_message(delete_after=0)
            embed = self._processes_view.render()
            if self._source_message is not None:
                await interaction.followup.edit_message(
                    message_id=self._source_message.id,
                    embed=embed,
                    view=self._processes_view,
                )

        await confirmation_request(
            self._processes_view.bot._("Are you sure you want to delete process '{}'?").format(target_name),
            interaction=interaction,
            on_confirmation=on_confirmation,
        )
