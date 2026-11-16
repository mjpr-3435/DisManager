from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import discord

from ....core.bootstrap.i18n import _
from ....core.files import (
    MAX_EDITABLE_TEXT_CHARS,
    FileActionError,
    create_directory,
    delete_entry,
    list_directory_entries,
    rename_entry,
    write_text_file,
)
from ...utils import confirmation_request
from .embed import ENTRIES_PER_PAGE

if TYPE_CHECKING:
    from .views import FilesView


class GoToPathModal(discord.ui.Modal):
    """Modal that navigates directly to a ``DisManager/...`` path."""

    path_input: discord.ui.TextInput[Any]

    def __init__(self, files_view: FilesView) -> None:
        super().__init__(title=_('Go to path'))
        self._files_view = files_view
        self.path_input = discord.ui.TextInput(
            label=_('Path'),
            style=discord.TextStyle.short,
            default=files_view.sandbox.to_virtual(files_view.path),
        )
        self.add_item(self.path_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        target = self._files_view.sandbox.resolve_virtual(self.path_input.value)
        if target is None:
            await interaction.response.send_message(
                _('✖ The path must exist inside `DisManager`. E.g.: `DisManager/logs`.'),
                ephemeral=True,
            )
            return

        await self._files_view.navigate(interaction, target)


class IndexActionModal(discord.ui.Modal):
    """Modal that opens or deletes an entry on the current page by index."""

    def __init__(self, files_view: FilesView, *, mode: Literal['open', 'delete']) -> None:
        title = _('Open by index') if mode == 'open' else _('Delete by index')
        super().__init__(title=title)
        self._files_view = files_view
        self._mode = mode
        self._kind_select: discord.ui.Select[Any] = discord.ui.Select(
            options=[
                discord.SelectOption(label=_('Directory'), value='dir', default=True),
                discord.SelectOption(label=_('File'), value='file'),
            ]
        )
        self._index_input: discord.ui.TextInput[Any] = discord.ui.TextInput(
            label=_('Index'),
            style=discord.TextStyle.short,
            placeholder=f'1 - {ENTRIES_PER_PAGE}',
            max_length=2,
        )
        self.add_item(discord.ui.Label(text=_('Type'), component=self._kind_select))
        self.add_item(self._index_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        raw_index = self._index_input.value.strip()
        if not raw_index.isdigit():
            await interaction.response.send_message(
                _('✖ The index must be a number.'),
                ephemeral=True,
            )
            return

        index = int(raw_index)
        try:
            dirs, files = list_directory_entries(self._files_view.path)
        except OSError as exc:
            await interaction.response.send_message(
                _('✖ Could not read directory: {}').format(exc),
                ephemeral=True,
            )
            return

        offset = (self._files_view.page - 1) * ENTRIES_PER_PAGE
        kind = self._kind_select.values[0]
        entries = (dirs if kind == 'dir' else files)[offset : offset + ENTRIES_PER_PAGE]

        if index < 1 or index > len(entries):
            await interaction.response.send_message(
                _('✖ Index out of range (1-{}).').format(len(entries)),
                ephemeral=True,
            )
            return

        target = entries[index - 1]
        if self._mode == 'open':
            await self._files_view.navigate(interaction, target)
            return

        await self._confirm_delete_entry(interaction, target)

    async def _confirm_delete_entry(self, interaction: discord.Interaction[Any], target: Path) -> None:
        sandbox = self._files_view.sandbox
        if sandbox.is_root(target) or not sandbox.is_within(target):
            return

        resolved = target.resolve()

        async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
            try:
                await asyncio.to_thread(delete_entry, sandbox, resolved)
            except FileActionError as exc:
                await confirm_interaction.response.edit_message(content=str(exc), embed=None, view=None)
                return

            await confirm_interaction.response.edit_message(delete_after=0)
            await self._files_view.navigate(interaction, self._files_view.path, page=self._files_view.page)

        await confirmation_request(
            _('Are you sure you want to delete `{}`?').format(sandbox.to_virtual(resolved)),
            interaction=interaction,
            on_confirmation=on_confirmation,
        )


class CreateDirModal(discord.ui.Modal):
    """Modal that creates a new subdirectory inside the current directory."""

    name_input: discord.ui.TextInput[Any]

    def __init__(self, files_view: FilesView) -> None:
        super().__init__(title=_('Create directory'))
        self._files_view = files_view
        self.name_input = discord.ui.TextInput(
            label=_('Directory name'),
            style=discord.TextStyle.short,
            placeholder=_('E.g.: backups'),
            max_length=100,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        try:
            create_directory(self._files_view.sandbox, self._files_view.path, self.name_input.value)
        except FileActionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await self._files_view.navigate(interaction, self._files_view.path, page=self._files_view.page)


class RenameModal(discord.ui.Modal):
    """Modal that renames the current directory or file."""

    name_input: discord.ui.TextInput[Any]

    def __init__(self, files_view: FilesView) -> None:
        title = _('Rename directory') if files_view.path.is_dir() else _('Rename file')
        super().__init__(title=title)
        self._files_view = files_view
        self.name_input = discord.ui.TextInput(
            label=_('New name'),
            style=discord.TextStyle.short,
            default=files_view.path.name,
            max_length=100,
        )
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        sandbox = self._files_view.sandbox
        target = self._files_view.path.resolve()
        if sandbox.is_root(target) or not sandbox.is_within(target):
            return

        try:
            dest = rename_entry(sandbox, target, self.name_input.value)
        except FileActionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        page = self._files_view.page if dest == target else 1
        await self._files_view.navigate(interaction, dest, page=page)


class UploadModal(discord.ui.Modal):
    """Modal that uploads up to 10 files into the current directory."""

    def __init__(self, files_view: FilesView) -> None:
        super().__init__(title=_('Upload files'))
        self._files_view = files_view
        self._overwrite: discord.ui.Checkbox[Any] = discord.ui.Checkbox(default=False)
        self._file_upload: discord.ui.FileUpload[Any] = discord.ui.FileUpload(min_values=1, max_values=10)

        self.add_item(
            discord.ui.Label(
                text=_('Overwrite?'),
                description=_('Replace existing files with the same name.'),
                component=self._overwrite,
            )
        )
        self.add_item(
            discord.ui.Label(
                text=_('Files'),
                description=_('Select up to 10 files to upload to the current directory.'),
                component=self._file_upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        attachments = self._file_upload.values
        total = len(attachments)
        status_msg = await interaction.followup.send(
            _('Processing files...'),
            ephemeral=True,
            wait=True,
        )

        overwrite = self._overwrite.value
        saved: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []

        for idx, attachment in enumerate(attachments, start=1):
            dest = self._files_view.sandbox.resolve_upload(
                attachment.filename,
                self._files_view.path,
            )
            if dest is None:
                failed.append(attachment.filename)
            elif dest.exists() and not overwrite:
                skipped.append(dest.name)
            else:
                try:
                    await attachment.save(dest)
                    saved.append(dest.name)
                except (OSError, discord.HTTPException):
                    failed.append(dest.name)

            if idx < total:
                await status_msg.edit(content=self._format_progress(idx, total, saved, skipped, failed))

        if interaction.message is not None:
            embed = self._files_view.render(self._files_view.path, page=self._files_view.page)
            await interaction.followup.edit_message(
                message_id=interaction.message.id,
                embed=embed,
                view=self._files_view,
            )

        await status_msg.edit(content=self._format_summary(saved, skipped, failed))

    def _format_progress(
        self,
        current: int,
        total: int,
        saved: list[str],
        skipped: list[str],
        failed: list[str],
    ) -> str:
        header = f'`[{current}/{total}]` {_("Processing files...")}'
        summary = self._format_summary(saved, skipped, failed)
        return f'{header}\n{summary}' if summary else header

    def _format_summary(self, saved: list[str], skipped: list[str], failed: list[str]) -> str:
        groups = (
            ('✔ Uploaded:', saved),
            ('✖ Already exists (skipped):', skipped),
            ('✖ Failed:', failed),
        )
        sections = [
            f'{_(label)}\n' + '\n'.join(f'- `{name}`' for name in names)
            for label, names in groups
            if names
        ]
        return '\n\n'.join(sections)


class EditFileModal(discord.ui.Modal):
    """Modal that edits a UTF-8 text file up to 4000 characters."""

    content_input: discord.ui.TextInput[Any]

    def __init__(self, files_view: FilesView, target: Path, content: str) -> None:
        super().__init__(title=_('Edit file'))
        self._files_view = files_view
        self._target = target
        self.content_input = discord.ui.TextInput(
            label=_('Content'),
            style=discord.TextStyle.paragraph,
            default=content,
            required=False,
            max_length=MAX_EDITABLE_TEXT_CHARS,
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        try:
            write_text_file(self._files_view.sandbox, self._target, self.content_input.value)
        except FileActionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_message(
            _('✔ Saved `{}`.').format(self._target.name),
            ephemeral=True,
        )
