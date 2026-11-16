from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import discord

from .embed import format_bytes


async def run_zip_command(
    target: Path,
    tmp_zip: Path,
    zip_name: str,
    confirm_interaction: discord.Interaction[Any],
    progress_template: str,
) -> int:
    """Compress ``target`` into ``tmp_zip`` via a terminal command with live progress."""
    total = await asyncio.to_thread(_count_entries, target, exclude=zip_name)
    if os.name == 'nt' or shutil.which('zip') is None:
        cmd = ['tar', '-a', '-v', '-cf', str(tmp_zip), '--exclude', zip_name, '.']
    else:
        cmd = ['zip', '-r', str(tmp_zip), '.', '-x', zip_name]

    def format_suffix() -> str:
        size_bytes = tmp_zip.stat().st_size if tmp_zip.exists() else 0
        return f' ({format_bytes(size_bytes)})' if size_bytes > 0 else ''

    return await _run_archive_command(
        cmd,
        cwd=target,
        total=total,
        confirm_interaction=confirm_interaction,
        progress_template=progress_template,
        suffix_fn=format_suffix,
    )


async def run_unzip_command(
    archive: Path,
    dest_dir: Path,
    confirm_interaction: discord.Interaction[Any],
    progress_template: str,
) -> int:
    """Extract ``archive`` into ``dest_dir`` via a terminal command with live progress."""
    total = await asyncio.to_thread(_count_zip_entries, archive)
    if os.name == 'nt' or shutil.which('unzip') is None:
        cmd = ['tar', '-v', '-xf', str(archive)]
    else:
        cmd = ['unzip', '-o', str(archive)]

    return await _run_archive_command(
        cmd,
        cwd=dest_dir,
        total=total,
        confirm_interaction=confirm_interaction,
        progress_template=progress_template,
    )


# =========================================
#            Internal Helpers
# =========================================


async def _run_archive_command(
    cmd: list[str],
    *,
    cwd: Path,
    total: int,
    confirm_interaction: discord.Interaction[Any],
    progress_template: str,
    suffix_fn: Callable[[], str] | None = None,
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
        prefix = f'`[{min(processed, total)}/{total}]` ' if total > 0 else ''
        suffix = suffix_fn() if suffix_fn is not None else ''
        with contextlib.suppress(discord.HTTPException):
            await confirm_interaction.edit_original_response(content=prefix + progress_template + suffix)

    await reader_task
    return await wait_task


def _count_entries(root: Path, *, exclude: str) -> int:
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
