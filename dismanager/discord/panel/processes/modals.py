from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal

import discord

from ....core.processes import ProcessConfig, ProcessConfigError, ProcessDeleteRequest, validate_process_data
from ...utils import confirmation_request

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
        event: Literal['new', 'update'] = 'update' if self._existing is not None else 'new'
        try:
            config = validate_process_data(
                name=name,
                start_command=self._start_input.value,
                stop_command=self._stop_input.value,
                blacklist=self._blacklist_input.value,
            )
            self._processes_view.bot._on_processes_edit(event, config)
        except ProcessConfigError as exc:
            await interaction.response.send_message(f'✖ {exc}', ephemeral=True)
            return

        await self._processes_view.refresh(interaction)


class DeleteProcessModal(discord.ui.Modal):
    """Modal with a process selector and folder-deletion checkbox."""

    def __init__(
        self,
        processes_view: ProcessesConfigView,
        processes: Sequence[ProcessConfig],
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
        self._delete_files_checkbox: discord.ui.Checkbox[Any] = discord.ui.Checkbox(default=False)
        self.add_item(discord.ui.Label(text=bot._('Process'), component=self._process_select))
        self.add_item(discord.ui.Label(text=bot._('Delete process folder too'), component=self._delete_files_checkbox))

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        bot = self._processes_view.bot
        target_name = self._process_select.values[0]
        delete_files = self._delete_files_checkbox.value

        async def finalize_delete(confirm_interaction: discord.Interaction[Any]) -> None:
            try:
                bot._on_processes_edit('delete', ProcessDeleteRequest(target_name, delete_files=delete_files))
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

        async def on_first_confirmation(first_confirm: discord.Interaction[Any]) -> None:
            if not delete_files:
                await finalize_delete(first_confirm)
                return

            class SecondConfirmView(discord.ui.View):
                def __init__(self) -> None:
                    super().__init__(timeout=120)

                @discord.ui.button(label='✔', style=discord.ButtonStyle.red)
                async def confirm_button(
                    self,
                    btn_interaction: discord.Interaction[Any],
                    _button: discord.ui.Button[Any],
                ) -> None:
                    await finalize_delete(btn_interaction)

                @discord.ui.button(label='✖', style=discord.ButtonStyle.gray)
                async def cancel_button(
                    self,
                    btn_interaction: discord.Interaction[Any],
                    _button: discord.ui.Button[Any],
                ) -> None:
                    await btn_interaction.response.edit_message(delete_after=0)

            warning = bot._(
                'This will ALSO permanently delete `DisManager/{}` and all its files. Are you sure?'
            ).format(target_name)
            await first_confirm.response.edit_message(
                embed=discord.Embed(description=warning, colour=0x2F3136),
                view=SecondConfirmView(),
            )

        await confirmation_request(
            bot._("Are you sure you want to delete process '{}'?").format(target_name),
            interaction=interaction,
            on_confirmation=on_first_confirmation,
        )
