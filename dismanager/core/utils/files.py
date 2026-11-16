from __future__ import annotations

import contextlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path


def dir_size_bytes(directory: Path) -> int:
    """Return the total size in bytes of regular files under ``directory``."""
    total = 0
    with contextlib.suppress(OSError):
        for entry in directory.rglob('*'):
            if entry.is_file() and not entry.is_symlink():
                with contextlib.suppress(OSError):
                    total += entry.stat().st_size
    return total


def remove_path(path: Path) -> None:
    """Delete a file, symlink, or directory tree at ``path`` if it exists."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def clear_directory_contents(directory: Path) -> None:
    """Remove all immediate children inside ``directory`` without deleting ``directory`` itself."""
    for child in directory.iterdir():
        remove_path(child)


def count_files(directory: Path, *, exclude_name: str | None = None) -> int:
    """Count regular files under ``directory``, optionally excluding a root-level filename."""
    total = 0
    for root, _, files in os.walk(directory):
        is_root = Path(root) == directory
        for filename in files:
            if is_root and exclude_name is not None and filename == exclude_name:
                continue
            total += 1
    return total


def copy_tree_with_progress(
    source_dir: Path,
    target_dir: Path,
    on_progress: Callable[[int, int], None] | None = None,
    *,
    total: int = 0,
    exclude_name: str | None = None,
) -> None:
    """Recursively copy ``source_dir`` to ``target_dir``, invoking ``on_progress(copied, total)``."""
    copied = 0
    target_dir.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(source_dir):
        rel = Path(root).relative_to(source_dir)
        dest_root = target_dir / rel
        dest_root.mkdir(parents=True, exist_ok=True)
        for dirname in dirs:
            (dest_root / dirname).mkdir(exist_ok=True)

        is_root = rel == Path('.')
        for filename in files:
            if is_root and exclude_name is not None and filename == exclude_name:
                continue
            shutil.copy2(Path(root) / filename, dest_root / filename)
            copied += 1
            if on_progress is not None:
                on_progress(copied, total)
