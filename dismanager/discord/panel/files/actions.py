from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

from ....core.bootstrap.i18n import _
from ....core.files import (
    FileActionError,
    compress_directory,
    delete_entry,
    extract_archive,
    is_editable_text,
    path_size_bytes,
    read_file_size,
    read_text_for_edit,
    to_dismanager_path,
)
from ....core.format import format_bytes
from ...utils import confirmation_request
from .modals import CreateDirModal, EditFileModal, IndexActionModal, RenameModal, UploadModal

if TYPE_CHECKING:
    from ...client import DisManagerClient
    from .views import FilesView  # noqa: F401


class DirectoryActionsSelect(discord.ui.Select['FilesView']):
    """Dropdown menu of actions available for the current directory."""

    def __init__(self, bot: DisManagerClient) -> None:
        options = [
            discord.SelectOption(
                label=_('Open by index'),
                value='cd',
                description=_('Open a directory or file by its index on this page'),
            ),
            discord.SelectOption(
                label=_('Calculate size'),
                value='size',
                description=_('Compute total size of this directory'),
            ),
            discord.SelectOption(
                label=_('Create directory'),
                value='mkdir',
                description=_('Create a new folder inside this directory'),
            ),
            discord.SelectOption(
                label=_('Upload files'),
                value='upload',
                description=_('Upload up to 10 files to this directory'),
            ),
            discord.SelectOption(
                label=_('Compress to .zip'),
                value='zip',
                description=_('Create a .zip archive of this directory'),
            ),
            discord.SelectOption(
                label=_('Rename directory'),
                value='rename',
                description=_('Rename this directory'),
            ),
            discord.SelectOption(
                label=_('Delete by index'),
                value='del',
                description=_('Delete a directory or file by its index on this page'),
            ),
            discord.SelectOption(
                label=_('Delete directory'),
                value='delete',
                description=_('Permanently delete this directory'),
            ),
        ]
        super().__init__(placeholder=_('Directory actions'), options=options, row=0)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        action = self.values[0]

        if action == 'cd':
            await interaction.response.send_modal(IndexActionModal(self.view, mode='open'))
        elif action == 'del':
            await interaction.response.send_modal(IndexActionModal(self.view, mode='delete'))
        elif action == 'size':
            await interaction.response.defer()
            size_text = format_bytes(await asyncio.to_thread(path_size_bytes, self.view.path))
            await self.view.navigate(interaction, self.view.path, page=self.view.page, size_text=size_text)
        elif action == 'mkdir':
            await interaction.response.send_modal(CreateDirModal(self.view))
        elif action == 'upload':
            await interaction.response.send_modal(UploadModal(self.view))
        elif action == 'zip':
            await self._confirm_zip(interaction)
        elif action == 'rename':
            await self._open_rename(interaction)
        elif action == 'delete':
            await self._confirm_delete(interaction)

    async def _open_rename(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        files_view = self.view
        target = files_view.path.resolve()
        if target == files_view.root:
            await interaction.response.send_message(
                _('✖ You cannot rename the root `DisManager` directory.'),
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(RenameModal(files_view))

    async def _confirm_delete(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        files_view = self.view
        target = files_view.path.resolve()
        if target == files_view.root:
            await interaction.response.send_message(
                _('✖ You cannot delete the root `DisManager` directory.'),
                ephemeral=True,
            )
            return
        await _confirm_delete_entry(files_view, interaction, target)

    async def _confirm_zip(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        files_view = self.view
        target = files_view.path.resolve()
        if not target.is_relative_to(files_view.root):
            return

        zip_name = f'{target.name}.zip'
        zip_path = target / zip_name

        async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
            progress_text = _('Compressing `{}`...').format(zip_name)
            await confirm_interaction.response.edit_message(content=progress_text, embed=None, view=None)

            async def on_progress(processed: int, total: int, size_bytes: int) -> None:
                prefix = f'`[{min(processed, total)}/{total}]` ' if total > 0 else ''
                suffix = f' ({format_bytes(size_bytes)})' if size_bytes > 0 else ''
                with contextlib.suppress(discord.HTTPException):
                    await confirm_interaction.edit_original_response(content=prefix + progress_text + suffix)

            try:
                rc = await compress_directory(target, zip_path, on_progress=on_progress)
                if rc != 0 or not zip_path.exists():
                    await confirm_interaction.edit_original_response(
                        content=_('✖ Failed to compress `{}` (exit code {}).').format(zip_name, rc)
                    )
                    return

                await files_view.navigate(interaction, target, page=files_view.page)
                await confirm_interaction.edit_original_response(
                    content=_('✔ Compressed into `{}`.').format(zip_name)
                )
            except OSError as exc:
                await confirm_interaction.edit_original_response(
                    content=_('✖ Failed to compress `{}`: {}').format(zip_name, exc)
                )

        await confirmation_request(
            _(
                'Are you sure you want to compress `{}` into `{}`? '
                'Any existing file with the same name will be overwritten.'
            ).format(to_dismanager_path(target, files_view.root), zip_name),
            interaction=interaction,
            on_confirmation=on_confirmation,
        )


class FileActionsSelect(discord.ui.Select['FilesView']):
    """Dropdown menu of actions available for an individual file."""

    def __init__(self, bot: DisManagerClient, path: Path) -> None:
        options = [
            discord.SelectOption(
                label=_('Download'),
                value='download',
                description=_('Send this file in an ephemeral message'),
            ),
            discord.SelectOption(
                label=_('Rename file'),
                value='rename',
                description=_('Rename this file'),
            ),
        ]
        if is_editable_text(path):
            options.append(
                discord.SelectOption(
                    label=_('Edit file'),
                    value='edit',
                    description=_('Edit this text file in a modal'),
                )
            )
        if path.suffix.lower() == '.zip':
            options.append(
                discord.SelectOption(
                    label=_('Unzip'),
                    value='unzip',
                    description=_('Extract this archive into the current folder'),
                )
            )
        options.append(
            discord.SelectOption(
                label=_('Delete file'),
                value='delete',
                description=_('Permanently delete this file'),
            )
        )
        super().__init__(placeholder=_('File actions'), options=options, row=0)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        action = self.values[0]
        target = self.view.path.resolve()

        if action == 'download':
            await self._download(interaction, target)
        elif action == 'rename':
            await interaction.response.send_modal(RenameModal(self.view))
        elif action == 'edit':
            await self._open_edit(interaction, target)
        elif action == 'unzip':
            await self._confirm_unzip(interaction, target)
        elif action == 'delete':
            await _confirm_delete_entry(self.view, interaction, target)

    async def _download(self, interaction: discord.Interaction[Any], target: Path) -> None:
        assert self.view is not None
        try:
            size = read_file_size(target)
        except FileActionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        limit = interaction.guild.filesize_limit if interaction.guild is not None else 10 * 1024 * 1024
        if size > limit:
            await interaction.response.send_message(
                _('✖ File is too large to send ({} > {}).').format(
                    format_bytes(size),
                    format_bytes(limit),
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(
            f'> **{to_dismanager_path(target, self.view.root)}**',
            file=discord.File(target),
            ephemeral=True,
        )

    async def _open_edit(self, interaction: discord.Interaction[Any], target: Path) -> None:
        assert self.view is not None
        try:
            content = read_text_for_edit(target)
        except FileActionError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.send_modal(EditFileModal(self.view, target, content))

    async def _confirm_unzip(self, interaction: discord.Interaction[Any], target: Path) -> None:
        assert self.view is not None
        files_view = self.view
        dest_dir = target.parent

        async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
            progress_text = _('Extracting `{}`...').format(target.name)
            await confirm_interaction.response.edit_message(content=progress_text, embed=None, view=None)

            async def on_progress(processed: int, total: int) -> None:
                prefix = f'`[{min(processed, total)}/{total}]` ' if total > 0 else ''
                with contextlib.suppress(discord.HTTPException):
                    await confirm_interaction.edit_original_response(content=prefix + progress_text)

            try:
                rc = await extract_archive(target, dest_dir, on_progress=on_progress)
                if rc != 0:
                    await confirm_interaction.edit_original_response(
                        content=_('✖ Failed to extract `{}` (exit code {}).').format(target.name, rc)
                    )
                    return

                await confirm_interaction.edit_original_response(
                    content=_('✔ Extracted `{}`.').format(target.name)
                )
            except OSError as exc:
                await confirm_interaction.edit_original_response(
                    content=_('✖ Failed to extract `{}`: {}').format(target.name, exc)
                )

        await confirmation_request(
            _(
                'Are you sure you want to extract `{}` into `{}`? '
                'Any existing files with the same name will be overwritten.'
            ).format(target.name, to_dismanager_path(dest_dir, files_view.root)),
            interaction=interaction,
            on_confirmation=on_confirmation,
        )


# =========================================
#            Internal Helpers
# =========================================


async def _confirm_delete_entry(
    files_view: FilesView,
    interaction: discord.Interaction[Any],
    target: Path,
) -> None:
    if not target.is_relative_to(files_view.root):
        return

    async def on_confirmation(confirm_interaction: discord.Interaction[Any]) -> None:
        try:
            await asyncio.to_thread(delete_entry, target, files_view.root)
        except FileActionError as exc:
            await confirm_interaction.response.edit_message(content=str(exc), embed=None, view=None)
            return

        await confirm_interaction.response.edit_message(delete_after=0)
        await files_view.navigate(interaction, target.parent)

    await confirmation_request(
        _('Are you sure you want to delete `{}`?').format(
            to_dismanager_path(target, files_view.root)
        ),
        interaction=interaction,
        on_confirmation=on_confirmation,
    )
