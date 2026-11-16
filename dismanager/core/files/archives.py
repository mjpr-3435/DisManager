from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path


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
    total = await asyncio.to_thread(_count_entries, target, exclude=zip_name)
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
