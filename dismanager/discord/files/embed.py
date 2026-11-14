from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from pathlib import Path

import discord

from .preview import populate_file_preview


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


def format_bytes(total: int) -> str:
    """Format a byte count into a human-readable size string."""
    units = ('B', 'KB', 'MB', 'GB', 'TB')
    unit_idx = min(int(math.log(total, 1024)), len(units) - 1) if total > 0 else 0
    return f'{total / (1024**unit_idx):.1f} {units[unit_idx]}'


def compute_path_size(path: Path) -> str:
    """Compute human-readable total size of a file or directory tree."""
    return format_bytes(_get_size_bytes(path))


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
    position = _get_file_position(path)
    if position is not None:
        idx, total_files = position
        file_page = idx // 99 + 1
        total_pages = max(1, math.ceil(total_files / 99))
        page_idx = (idx % 99) + 1
        file_label = (
            f'File {page_idx:02d} (#{idx + 1}/{total_files})'
            if total_pages > 1
            else f'File {idx + 1}/{total_files}'
        )
        footer_parts.extend([file_label, f'Page {file_page}/{total_pages}'])
    embed.set_footer(text=' | '.join(footer_parts))


def _get_file_position(path: Path) -> tuple[int, int] | None:
    try:
        _, sibling_files = list_directory_entries(path.parent)
        return sibling_files.index(path), len(sibling_files)
    except (OSError, ValueError):
        return None


def _get_size_bytes(path: Path) -> int:
    try:
        if not path.is_dir():
            return path.stat(follow_symlinks=False).st_size
    except OSError:
        return 0

    total = 0
    stack: list[Path] = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


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
