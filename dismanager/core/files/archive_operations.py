from __future__ import annotations

import asyncio
import os
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

TAR_SUFFIXES = ('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')


def is_archive_file(path: Path) -> bool:
    """Return whether ``path`` uses a supported zip or tar archive extension."""
    suffix = path.suffix.lower()
    return suffix == '.zip' or path.name.lower().endswith(TAR_SUFFIXES)


async def compress_directory(
    target: Path,
    dest_zip: Path,
    *,
    on_progress: Callable[[int, int, int], Awaitable[None]] | None = None,
) -> int:
    """Compress ``target`` into ``dest_zip`` atomically, reporting progress periodically.

    ``on_progress`` receives ``(processed_entries, total_entries, archive_bytes)``.
    Returns the archiver subprocess exit code.
    """
    zip_name = dest_zip.name
    total = await asyncio.to_thread(_count_archive_sources, target, exclude=zip_name)
    tmp_dir = Path(tempfile.mkdtemp(prefix='dismanager_zip_'))
    tmp_zip = tmp_dir / zip_name

    if os.name == 'nt' or shutil.which('zip') is None:
        cmd = ['tar', '-a', '-v', '-cf', str(tmp_zip), '--exclude', zip_name, '.']
    else:
        cmd = ['zip', '-r', str(tmp_zip), '.', '-x', zip_name]

    try:
        async def report_progress(processed: int) -> None:
            if on_progress is None:
                return
            size_bytes = tmp_zip.stat().st_size if tmp_zip.exists() else 0
            await on_progress(processed, total, size_bytes)

        rc = await _run_archive_command(
            cmd,
            cwd=target,
            on_tick=report_progress if on_progress is not None else None,
        )
        if rc == 0 and tmp_zip.exists():
            await asyncio.to_thread(shutil.move, str(tmp_zip), str(dest_zip))
        return rc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def extract_archive(
    archive: Path,
    dest_dir: Path,
    *,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> int:
    """Extract ``archive`` into ``dest_dir``, reporting progress periodically.

    ``on_progress`` receives ``(processed_entries, total_entries)``.
    Returns the extractor subprocess exit code.
    """
    total = await asyncio.to_thread(_count_zip_entries, archive)
    if os.name == 'nt' or shutil.which('unzip') is None:
        cmd = ['tar', '-v', '-xf', str(archive)]
    else:
        cmd = ['unzip', '-o', str(archive)]

    async def report_progress(processed: int) -> None:
        if on_progress is not None:
            await on_progress(processed, total)

    return await _run_archive_command(
        cmd,
        cwd=dest_dir,
        on_tick=report_progress if on_progress is not None else None,
    )


def read_archive_entries(path: Path) -> list[tuple[list[str], bool]]:
    """Return normalized ``(path_parts, is_dir)`` entries from a ``.zip`` or ``.tar*`` archive."""
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as zf:
            return [
                (parts, info.is_dir())
                for info in zf.infolist()
                if (parts := [p for p in info.filename.strip('/').split('/') if p and p != '.'])
            ]

    with tarfile.open(path, 'r:*') as tf:
        return [
            (parts, member.isdir())
            for member in tf.getmembers()
            if (parts := [p for p in member.name.strip('/').split('/') if p and p != '.'])
        ]


def build_archive_tree_text(path: Path, *, max_chars: int = 3200) -> str | None:
    """Render an ASCII tree of entries inside ``path``, or ``None`` if the archive is empty."""
    entries = read_archive_entries(path)
    if not entries:
        return None

    tree: dict[str, Any] = {}
    for parts, is_dir in entries:
        _insert_tree_node(tree, parts, is_dir=is_dir)

    lines = [path.name]
    _render_ascii_tree(tree, prefix='', lines=lines)

    output_lines: list[str] = []
    char_count = 0
    truncated_entries = 0

    for idx, line in enumerate(lines):
        next_len = char_count + len(line) + 1
        if next_len > max_chars and idx > 1:
            truncated_entries = len(lines) - idx
            break
        output_lines.append(line)
        char_count = next_len

    if truncated_entries > 0:
        output_lines.append(f'... (+{truncated_entries} more entries)')

    return '\n'.join(output_lines)


# =========================================
#            Internal Helpers
# =========================================


async def _run_archive_command(
    cmd: list[str],
    *,
    cwd: Path,
    on_tick: Callable[[int], Awaitable[None]] | None = None,
) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    processed = 0

    async def _consume_output() -> None:
        nonlocal processed
        if proc.stdout is None:
            return
        while raw_line := await proc.stdout.readline():
            if raw_line.strip():
                processed += 1

    reader_task = asyncio.create_task(_consume_output())
    wait_task = asyncio.create_task(proc.wait())

    while not wait_task.done():
        await asyncio.sleep(0.8)
        if wait_task.done():
            break
        if on_tick is not None:
            await on_tick(processed)

    await reader_task
    return await wait_task


def _count_archive_sources(root: Path, *, exclude: str) -> int:
    count = 1
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.name == exclude and current == root:
                        continue
                    count += 1
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return count


def _count_zip_entries(archive: Path) -> int:
    try:
        with zipfile.ZipFile(archive, 'r') as zf:
            return len(zf.infolist())
    except (OSError, zipfile.BadZipFile):
        return 0


def _insert_tree_node(root: dict[str, Any], parts: list[str], *, is_dir: bool) -> None:
    node = root
    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        existing = node.get(part)
        if is_last and not is_dir:
            if existing is None:
                node[part] = None
            return
        if not isinstance(existing, dict):
            existing = {}
            node[part] = existing
        node = existing


def _render_ascii_tree(node: dict[str, Any], *, prefix: str, lines: list[str]) -> None:
    items = sorted(node.items(), key=lambda item: (not isinstance(item[1], dict), item[0].lower()))
    last_idx = len(items) - 1
    for idx, (name, child) in enumerate(items):
        is_last = idx == last_idx
        connector = '`-- ' if is_last else '|-- '
        if isinstance(child, dict):
            lines.append(f'{prefix}{connector}{name}/')
            child_prefix = f'{prefix}{"    " if is_last else "|   "}'
            _render_ascii_tree(child, prefix=child_prefix, lines=lines)
        else:
            lines.append(f'{prefix}{connector}{name}')
