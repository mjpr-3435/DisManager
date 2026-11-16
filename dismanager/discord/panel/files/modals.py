from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import discord

from ....core.bootstrap.i18n import _
from ...utils import confirmation_request
from .embed import list_directory_entries, to_dismanager_path

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
            default=to_dismanager_path(files_view.path, files_view.root),
        )
        self.add_item(self.path_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        target = _resolve_dismanager_path(self.path_input.value, self._files_view.root)
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
            placeholder='1 - 99',
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

        offset = (self._files_view.page - 1) * 99
        kind = self._kind_select.values[0]
        entries = (dirs if kind == 'dir' else files)[offset : offset + 99]

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
        resolved = target.resolve()
        if resolved == self._files_view.root or not resolved.is_relative_to(self._files_view.root):
            return

        async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
            try:
                if resolved.is_dir():
                    await asyncio.to_thread(shutil.rmtree, resolved)
                else:
                    await asyncio.to_thread(resolved.unlink)
            except OSError as exc:
                await confirm_interaction.response.edit_message(
                    content=_('✖ Could not delete `{}`: {}').format(resolved.name, exc),
                    embed=None,
                    view=None,
                )
                return

            await confirm_interaction.response.edit_message(delete_after=0)
            await self._files_view.navigate(interaction, self._files_view.path, page=self._files_view.page)

        await confirmation_request(
            _('Are you sure you want to delete `{}`?').format(
                to_dismanager_path(resolved, self._files_view.root)
            ),
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
        name = self.name_input.value.strip()
        target_dir = self._files_view.path.resolve()
        dest = (target_dir / name).resolve()
        if not _is_valid_entry_name(name) or dest.parent != target_dir:
            await interaction.response.send_message(
                _('✖ Invalid directory name.'),
                ephemeral=True,
            )
            return

        if dest.exists():
            await interaction.response.send_message(
                _('✖ `{}` already exists.').format(name),
                ephemeral=True,
            )
            return

        try:
            dest.mkdir()
        except OSError as exc:
            await interaction.response.send_message(
                _('✖ Could not create directory: {}').format(exc),
                ephemeral=True,
            )
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
        new_name = self.name_input.value.strip()
        target = self._files_view.path.resolve()
        if target == self._files_view.root or not target.is_relative_to(self._files_view.root):
            return

        if new_name == target.name:
            await self._files_view.navigate(interaction, target, page=self._files_view.page)
            return

        dest = (target.parent / new_name).resolve()
        if not _is_valid_entry_name(new_name) or dest.parent != target.parent:
            await interaction.response.send_message(
                _('✖ Invalid name.'),
                ephemeral=True,
            )
            return

        if dest.exists():
            await interaction.response.send_message(
                _('✖ `{}` already exists.').format(new_name),
                ephemeral=True,
            )
            return

        try:
            target.rename(dest)
        except OSError as exc:
            await interaction.response.send_message(
                _('✖ Could not rename: {}').format(exc),
                ephemeral=True,
            )
            return

        await self._files_view.navigate(interaction, dest)


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
        target_dir = self._files_view.path.resolve()
        saved: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []

        for idx, attachment in enumerate(attachments, start=1):
            filename = Path(attachment.filename).name
            dest = (target_dir / filename).resolve()
            if not filename or not dest.is_relative_to(target_dir):
                failed.append(attachment.filename)
            elif dest.exists() and not overwrite:
                skipped.append(filename)
            else:
                try:
                    await attachment.save(dest)
                    saved.append(filename)
                except (OSError, discord.HTTPException):
                    failed.append(filename)

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
            max_length=4000,
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        try:
            self._target.write_text(self.content_input.value, encoding='utf-8')
        except OSError as exc:
            await interaction.response.send_message(
                _('✖ Could not save file: {}').format(exc),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            _('✔ Saved `{}`.').format(self._target.name),
            ephemeral=True,
        )


# =========================================
#            Internal Helpers
# =========================================


def _is_valid_entry_name(name: str) -> bool:
    return bool(name) and name not in {'.', '..'} and not any(ch in name for ch in '<>:"/\\|?*')


def _resolve_dismanager_path(raw_path: str, root: Path) -> Path | None:
    cleaned = raw_path.strip().replace('\\', '/')
    parts = [part for part in cleaned.split('/') if part]
    if not parts or parts[0] != 'DisManager':
        return None

    candidate = root.joinpath(*parts[1:]).resolve()
    if not candidate.is_relative_to(root) or not candidate.exists():
        return None
    return candidate
