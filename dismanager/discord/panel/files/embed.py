from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import discord

from ....core.files import get_sibling_files, list_directory_entries, to_dismanager_path
from ....core.format import format_bytes
from .preview import populate_file_preview

ENTRIES_PER_PAGE = 99


def get_max_page(dir_count: int, file_count: int) -> int:
    """Return the total number of pages for the given directory and file counts."""
    return max(1, math.ceil(dir_count / ENTRIES_PER_PAGE), math.ceil(file_count / ENTRIES_PER_PAGE))


def build_files_embed(
    path: Path,
    root: Path,
    page: int,
    *,
    size_text: str | None,
) -> discord.Embed:
    """Build the Files navigation embed for a directory or single file."""
    embed = discord.Embed(
        title=f'> **{to_dismanager_path(path, root)}**',
        colour=0x2F3136,
    )

    if path.is_dir():
        _populate_directory_embed(embed, path, page, size_text=size_text)
    else:
        _populate_file_embed(embed, path)

    return embed


# =========================================
#            Internal Helpers
# =========================================


def _populate_directory_embed(
    embed: discord.Embed,
    path: Path,
    page: int,
    *,
    size_text: str | None,
) -> None:
    try:
        dirs, files = list_directory_entries(path)
    except OSError as exc:
        embed.description = f'```\n{exc}```'
        return

    max_page = get_max_page(len(dirs), len(files))
    current_page = min(max(page, 1), max_page)

    for col in _build_columns(dirs, '📦', current_page):
        embed.add_field(inline=True, name='', value=col)
    for col in _build_columns(files, '📄', current_page):
        embed.add_field(inline=True, name='', value=col)

    footer_parts = [f'Dirs: {len(dirs)}', f'Files: {len(files)}']
    if size_text is not None:
        footer_parts.insert(0, f'Size: {size_text}')
    if max_page > 1:
        footer_parts.append(f'Page {current_page}/{max_page}')
    embed.set_footer(text=' | '.join(footer_parts))


def _populate_file_embed(embed: discord.Embed, path: Path) -> None:
    try:
        stat = path.stat(follow_symlinks=False)
    except OSError as exc:
        embed.description = f'```\n{exc}```'
        return

    populate_file_preview(embed, path, stat.st_size)
    size = format_bytes(stat.st_size)
    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).astimezone().strftime('%Y-%m-%d %H:%M')
    footer_parts = [f'Size: {size}', f'Modified: {modified}']
    sibling_info = get_sibling_files(path)
    if sibling_info is not None:
        files, idx = sibling_info
        total_files = len(files)
        file_page = idx // ENTRIES_PER_PAGE + 1
        total_pages = max(1, math.ceil(total_files / ENTRIES_PER_PAGE))
        page_idx = (idx % ENTRIES_PER_PAGE) + 1
        file_label = (
            f'File {page_idx:02d} (#{idx + 1}/{total_files})'
            if total_pages > 1
            else f'File {idx + 1}/{total_files}'
        )
        footer_parts.extend([file_label, f'Page {file_page}/{total_pages}'])
    embed.set_footer(text=' | '.join(footer_parts))


def _build_columns(items: list[Path], emoji: str, page: int) -> list[str]:
    offset = (page - 1) * ENTRIES_PER_PAGE
    paginated = items[offset : offset + ENTRIES_PER_PAGE]
    if not paginated:
        return []

    columns = [paginated[i::3] for i in range(3)]
    return [
        '\n\n'.join(f'`{idx * 3 + col_idx + 1:02d} {emoji} {item.name[:14]}`' for idx, item in enumerate(col))
        or '\u200b'
        for col_idx, col in enumerate(columns)
    ]
