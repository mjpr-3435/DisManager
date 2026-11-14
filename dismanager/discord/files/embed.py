from __future__ import annotations

import math
from pathlib import Path

import discord


def to_dismanager_path(path: Path, root: Path) -> str:
    """Format a filesystem path under ``root`` with the ``DisManager`` mask."""
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved == resolved_root:
        return 'DisManager'

    rel = resolved.relative_to(resolved_root)
    return f'DisManager/{rel.as_posix()}'


def list_directory_entries(path: Path) -> tuple[list[Path], list[Path]]:
    """Return sorted ``(dirs, files)`` entries inside ``path``."""
    entries = sorted(path.iterdir(), key=lambda entry: entry.name.lower())
    dirs = [entry for entry in entries if entry.is_dir()]
    files = [entry for entry in entries if entry.is_file()]
    return dirs, files


def get_max_page(dir_count: int, file_count: int) -> int:
    """Return the total number of pages for the given directory and file counts."""
    return max(1, math.ceil(dir_count / 99), math.ceil(file_count / 99))


def build_files_embed(path: Path, root: Path, page: int = 1) -> discord.Embed:
    """Build the Files navigation embed for a directory or single file."""
    embed = discord.Embed(
        title=f'> **{to_dismanager_path(path, root)}**',
        colour=0x2F3136,
    )

    if path.is_dir():
        _populate_directory_embed(embed, path, page)

    return embed


# =========================================
#            Internal Helpers
# =========================================


def _populate_directory_embed(embed: discord.Embed, path: Path, page: int) -> None:
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

    footer = f'Dirs: {len(dirs)} | Files: {len(files)}'
    if max_page > 1:
        footer = f'{footer} | Page {current_page}/{max_page}'
    embed.set_footer(text=footer)


def _build_columns(items: list[Path], emoji: str, page: int) -> list[str]:
    offset = (page - 1) * 99
    paginated = items[offset : offset + 99]
    if not paginated:
        return []

    columns = [paginated[i::3] for i in range(3)]
    return [
        '\n\n'.join(f'`{idx * 3 + col_idx + 1:02d} {emoji} {item.name[:14]}`' for idx, item in enumerate(col))
        or '\u200b'
        for col_idx, col in enumerate(columns)
    ]
