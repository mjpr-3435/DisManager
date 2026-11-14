from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

from .actions import DirectoryActionsSelect, FileActionsSelect
from .embed import build_files_embed, get_max_page, list_directory_entries
from .modals import GoToPathModal
from .preview import build_file_attachment

if TYPE_CHECKING:
    from ..client import DisManagerClient


class FilesView(discord.ui.View):
    """Interactive file-navigation view with directory/file bifurcation."""

    def __init__(self, bot: DisManagerClient) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.root = Path.cwd().resolve()
        self.path = self.root
        self.page = 1
        self._max_page = 1
        self._select_targets: list[Path] = []
        self.render(self.root, page=1)

    def render(self, path: Path, *, page: int = 1, size_text: str | None = None) -> discord.Embed:
        """Update view controls for ``path`` (file or directory) and return its embed."""
        self.path = _clamp_to_root(path, self.root)
        self.clear_items()
        self._select_targets = []

        if self.path.is_dir():
            self._build_directory_items(page)
        else:
            self.page = 1
            self._max_page = 1
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
        attachment = build_file_attachment(self.path)
        message = interaction.message
        if message is not None:
            await interaction.followup.edit_message(
                message_id=message.id,
                embed=embed,
                view=self,
                attachments=[attachment] if attachment is not None else [],
            )

    # =========================================
    #            Internal Helpers
    # =========================================

    def _build_directory_items(self, page: int) -> None:
        try:
            dirs, files = list_directory_entries(self.path)
        except OSError:
            dirs, files = [], []

        self._max_page = get_max_page(len(dirs), len(files))
        self.page = min(max(page, 1), self._max_page)

        self.add_item(DirectoryActionsSelect(self.bot))

        options = self._build_select_options(dirs, files)
        if options:
            self.add_item(_FileSelect(self.bot._('Select a file'), options))

        self.add_item(_BackButton(disabled=self.path == self.root, row=2))
        self.add_item(_UpdateButton(row=2))
        self.add_item(_PathButton(row=2))

        if self._max_page > 1:
            self._add_pagination_buttons()

    def _build_file_items(self) -> None:
        self.add_item(FileActionsSelect(self.bot, self.path))
        self.add_item(_BackButton(disabled=self.path == self.root, row=1))
        self.add_item(_UpdateButton(row=1))
        self.add_item(_PathButton(row=1))
        self._add_sibling_file_buttons()

    def _add_sibling_file_buttons(self) -> None:
        sibling_info = _get_sibling_files(self.path)
        if sibling_info is None:
            return
        files, idx = sibling_info
        if len(files) <= 1:
            return

        if len(files) > 2:
            self.add_item(_SiblingFileButton('<<', target_path=files[0], disabled=idx <= 0))

        self.add_item(_SiblingFileButton('<', target_path=files[max(0, idx - 1)], disabled=idx <= 0))
        self.add_item(
            _SiblingFileButton(
                '>',
                target_path=files[min(len(files) - 1, idx + 1)],
                disabled=idx >= len(files) - 1,
            )
        )

        if len(files) > 2:
            self.add_item(_SiblingFileButton('>>', target_path=files[-1], disabled=idx >= len(files) - 1))

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
        if self._max_page > 2:
            self.add_item(_PageButton('<<', target_page=1, disabled=self.page <= 1))

        self.add_item(_PageButton('<', target_page=max(1, self.page - 1), disabled=self.page <= 1))
        self.add_item(
            _PageButton(
                '>',
                target_page=min(self._max_page, self.page + 1),
                disabled=self.page >= self._max_page,
            )
        )

        if self._max_page > 2:
            self.add_item(_PageButton('>>', target_page=self._max_page, disabled=self.page >= self._max_page))


def _clamp_to_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(root) else root


def _get_sibling_files(path: Path) -> tuple[list[Path], int] | None:
    try:
        _, files = list_directory_entries(path.parent)
        return files, files.index(path)
    except (OSError, ValueError):
        return None


class _FileSelect(discord.ui.Select[FilesView]):
    def __init__(self, placeholder: str, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder=placeholder, options=options, row=1)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        target = self.view._select_targets[int(self.values[0])]
        await self.view.navigate(interaction, target)


class _BackButton(discord.ui.Button[FilesView]):
    def __init__(self, *, disabled: bool, row: int) -> None:
        super().__init__(label='⬅️', style=discord.ButtonStyle.gray, disabled=disabled, row=row)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        parent_page = 1
        if not self.view.path.is_dir():
            sibling_info = _get_sibling_files(self.view.path)
            if sibling_info is not None:
                _, idx = sibling_info
                parent_page = idx // 99 + 1
        await self.view.navigate(interaction, self.view.path.parent, page=parent_page)


class _UpdateButton(discord.ui.Button[FilesView]):
    def __init__(self, *, row: int) -> None:
        super().__init__(label='🔄', style=discord.ButtonStyle.gray, row=row)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, self.view.path, page=self.view.page)


class _PathButton(discord.ui.Button[FilesView]):
    def __init__(self, *, row: int) -> None:
        super().__init__(label='📌', style=discord.ButtonStyle.gray, row=row)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.send_modal(GoToPathModal(self.view))


class _PageButton(discord.ui.Button[FilesView]):
    def __init__(self, label: str, *, target_page: int, disabled: bool) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.gray, row=3, disabled=disabled)
        self._target_page = target_page

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, self.view.path, page=self._target_page)


class _SiblingFileButton(discord.ui.Button[FilesView]):
    def __init__(self, label: str, *, target_path: Path, disabled: bool) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.gray, row=2, disabled=disabled)
        self._target_path = target_path

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, self._target_path)
