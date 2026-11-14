from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

from .embed import (
    build_files_embed,
    compute_path_size,
    get_max_page,
    list_directory_entries,
    to_dismanager_path,
)

if TYPE_CHECKING:
    from ..client import DisManagerClient


class FilesView(discord.ui.View):
    """Interactive file-navigation view with directory/file bifurcation."""

    def __init__(self, bot: DisManagerClient, path: Path | None = None, *, root: Path | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.root = (root or Path.cwd()).resolve()
        self.path = self.root
        self.page = 1
        self.max_page = 1
        self._select_targets: list[Path] = []
        self.render(path or self.root, page=1)

    def render(self, path: Path, *, page: int = 1, size_text: str | None = None) -> discord.Embed:
        """Update view controls for ``path`` (file or directory) and return its embed."""
        self.path = _clamp_to_root(path, self.root)
        self.clear_items()
        self._select_targets = []

        if self.path.is_dir():
            self._build_directory_items(page)
        else:
            self.page = 1
            self.max_page = 1
            self._build_file_items()

        return build_files_embed(self.path, self.root, self.page, size_text=size_text)

    async def navigate(
        self,
        interaction: discord.Interaction[Any],
        path: Path,
        *,
        page: int = 1,
        size_text: str | None = None,
    ) -> None:
        """Render ``path`` and edit the ephemeral Files message."""
        if not interaction.response.is_done():
            await interaction.response.defer()

        embed = self.render(path, page=page, size_text=size_text)
        message = interaction.message
        if message is not None:
            await interaction.followup.edit_message(
                message_id=message.id,
                embed=embed,
                view=self,
            )

    # =========================================
    #            Internal Helpers
    # =========================================

    def _build_directory_items(self, page: int) -> None:
        try:
            dirs, files = list_directory_entries(self.path)
        except OSError:
            dirs, files = [], []

        self.max_page = get_max_page(len(dirs), len(files))
        self.page = min(max(page, 1), self.max_page)

        options = self._build_select_options(dirs, files)
        if options:
            self.add_item(_FileSelect(self.bot._('Select a file'), options))

        self.add_item(_BackButton(disabled=self.path == self.root))
        self.add_item(_UpdateButton())
        self.add_item(_PathButton())
        self.add_item(_SizeButton())
        self.add_item(_UploadButton())

        if self.max_page > 1:
            self._add_pagination_buttons()

    def _build_file_items(self) -> None:
        self.add_item(_BackButton(disabled=self.path == self.root))
        self.add_item(_UpdateButton())
        self.add_item(_PathButton())

    def _build_select_options(self, dirs: list[Path], files: list[Path]) -> list[discord.SelectOption]:
        offset = (self.page - 1) * 99
        page_dirs = dirs[offset : offset + 99]
        page_files = files[offset : offset + 99]
        targets = [*page_dirs, *page_files][:25]
        self._select_targets = targets

        options: list[discord.SelectOption] = []
        for idx, entry in enumerate(targets):
            emoji = '📦' if entry.is_dir() else '📄'
            name = entry.name if len(entry.name) < 90 else f'{entry.name[:87]}...'
            options.append(discord.SelectOption(label=f'{emoji} {name}', value=str(idx)))
        return options

    def _add_pagination_buttons(self) -> None:
        if self.max_page > 2:
            self.add_item(_PageButton('<<', target_page=1, disabled=self.page <= 1))

        self.add_item(_PageButton('<', target_page=max(1, self.page - 1), disabled=self.page <= 1))
        self.add_item(
            _PageButton(
                '>',
                target_page=min(self.max_page, self.page + 1),
                disabled=self.page >= self.max_page,
            )
        )

        if self.max_page > 2:
            self.add_item(_PageButton('>>', target_page=self.max_page, disabled=self.page >= self.max_page))


def _clamp_to_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root) else root


def _resolve_dismanager_path(raw_path: str, root: Path) -> Path | None:
    cleaned = raw_path.strip().replace('\\', '/')
    parts = [part for part in cleaned.split('/') if part]
    if not parts or parts[0] != 'DisManager':
        return None

    candidate = root.joinpath(*parts[1:]).resolve()
    if not candidate.is_relative_to(root) or not candidate.exists():
        return None
    return candidate


class _FileSelect(discord.ui.Select[FilesView]):
    def __init__(self, placeholder: str, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder=placeholder, options=options)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        target = self.view._select_targets[int(self.values[0])]
        await self.view.navigate(interaction, target)


class _BackButton(discord.ui.Button[FilesView]):
    def __init__(self, *, disabled: bool = False) -> None:
        super().__init__(label='⬅️', style=discord.ButtonStyle.gray, disabled=disabled)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, self.view.path.parent)


class _UpdateButton(discord.ui.Button[FilesView]):
    def __init__(self) -> None:
        super().__init__(label='🔄', style=discord.ButtonStyle.gray)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, self.view.path, page=self.view.page)


class _PathButton(discord.ui.Button[FilesView]):
    def __init__(self) -> None:
        super().__init__(label='📌', style=discord.ButtonStyle.gray)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.send_modal(_GoToPathModal(self.view))


class _SizeButton(discord.ui.Button[FilesView]):
    def __init__(self) -> None:
        super().__init__(label='Size', style=discord.ButtonStyle.gray)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.defer()
        size_text = await asyncio.to_thread(compute_path_size, self.view.path)
        await self.view.navigate(interaction, self.view.path, page=self.view.page, size_text=size_text)


class _UploadButton(discord.ui.Button[FilesView]):
    def __init__(self) -> None:
        super().__init__(label='Upload', style=discord.ButtonStyle.gray)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.send_modal(_UploadModal(self.view))


class _PageButton(discord.ui.Button[FilesView]):
    def __init__(self, label: str, *, target_page: int, disabled: bool) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.gray, row=2, disabled=disabled)
        self._target_page = target_page

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, self.view.path, page=self._target_page)


class _GoToPathModal(discord.ui.Modal):
    path_input: discord.ui.TextInput[Any]

    def __init__(self, files_view: FilesView) -> None:
        super().__init__(title=files_view.bot._('Go to path'))
        self._files_view = files_view
        self.path_input = discord.ui.TextInput(
            label=files_view.bot._('Path'),
            style=discord.TextStyle.short,
            default=to_dismanager_path(files_view.path, files_view.root),
        )
        self.add_item(self.path_input)

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        target = _resolve_dismanager_path(self.path_input.value, self._files_view.root)
        if target is None:
            await interaction.response.send_message(
                self._files_view.bot._('✖ The path must exist inside `DisManager`. E.g.: `DisManager/logs`.'),
                ephemeral=True,
            )
            return

        await self._files_view.navigate(interaction, target)


class _UploadModal(discord.ui.Modal):
    def __init__(self, files_view: FilesView) -> None:
        super().__init__(title=files_view.bot._('Upload files'))
        self._files_view = files_view
        self._overwrite: discord.ui.Checkbox[Any] = discord.ui.Checkbox(default=False)
        self._file_upload: discord.ui.FileUpload[Any] = discord.ui.FileUpload(min_values=1, max_values=10)

        self.add_item(
            discord.ui.Label(
                text=files_view.bot._('Overwrite?'),
                description=files_view.bot._('Replace existing files with the same name.'),
                component=self._overwrite,
            )
        )
        self.add_item(
            discord.ui.Label(
                text=files_view.bot._('Files'),
                description=files_view.bot._('Select up to 10 files to upload to the current directory.'),
                component=self._file_upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction[Any]) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        attachments = self._file_upload.values
        total = len(attachments)
        status_msg = await interaction.followup.send(
            self._files_view.bot._('Processing files...'),
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
                await status_msg.edit(
                    content=self._format_progress(idx, total, saved, skipped, failed),
                )

        if saved and interaction.message is not None:
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
        header = f'`[{current}/{total}]` {self._files_view.bot._("Processing files...")}'
        summary = self._format_summary(saved, skipped, failed)
        return f'{header}\n{summary}' if summary else header

    def _format_summary(self, saved: list[str], skipped: list[str], failed: list[str]) -> str:
        groups = (
            ('✔ Uploaded:', saved),
            ('✖ Already exists (skipped):', skipped),
            ('✖ Failed:', failed),
        )
        sections = [
            f"{self._files_view.bot._(label)}\n" + '\n'.join(f'- `{name}`' for name in names)
            for label, names in groups
            if names
        ]
        return '\n\n'.join(sections)
