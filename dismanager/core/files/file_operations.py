from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from ..bootstrap.i18n import _
from .sandbox_paths import FileActionError, SandboxPaths


def path_size_bytes(path: Path) -> int:
    """Return total byte size of a file or directory tree without following symlinks."""
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
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
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
    for root, _dirs, files in os.walk(directory):
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


def list_directory_entries(path: Path) -> tuple[list[Path], list[Path]]:
    """Return sorted ``(dirs, files)`` entries inside ``path``."""
    entries = sorted(path.iterdir(), key=lambda entry: entry.name.lower())
    dirs = [entry for entry in entries if entry.is_dir()]
    files = [entry for entry in entries if entry.is_file()]
    return dirs, files


def get_sibling_files(path: Path) -> tuple[list[Path], int] | None:
    """Return ``(sibling_files, index)`` for ``path`` inside its parent directory."""
    try:
        _, files = list_directory_entries(path.parent)
        return files, files.index(path)
    except (OSError, ValueError):
        return None


def read_file_size(path: Path) -> int:
    """Return the byte size of ``path`` or raise :class:`FileActionError`."""
    try:
        return path.stat().st_size
    except OSError as exc:
        raise FileActionError(_('✖ Could not read file: {}').format(exc)) from exc


def create_directory(sandbox: SandboxPaths, parent: Path, raw_name: str) -> Path:
    """Create a validated subdirectory under ``parent`` within ``sandbox``."""
    dest = sandbox.resolve_new_child(parent, raw_name, invalid_message=_('✖ Invalid directory name.'))
    try:
        dest.mkdir()
    except OSError as exc:
        raise FileActionError(_('✖ Could not create directory: {}').format(exc)) from exc
    return dest


def rename_entry(sandbox: SandboxPaths, target: Path, raw_new_name: str) -> Path:
    """Rename a directory or file within ``sandbox`` and return its new path."""
    resolved, dest = sandbox.resolve_rename_target(target, raw_new_name)
    if dest == resolved:
        return resolved

    try:
        resolved.rename(dest)
    except OSError as exc:
        raise FileActionError(_('✖ Could not rename: {}').format(exc)) from exc
    return dest


def delete_entry(sandbox: SandboxPaths, target: Path) -> None:
    """Delete a file or directory within ``sandbox``."""
    resolved = sandbox.require_mutable(
        target,
        root_error=_('✖ You cannot delete the root `DisManager` directory.'),
    )
    try:
        remove_path(resolved)
    except OSError as exc:
        raise FileActionError(_('✖ Could not delete `{}`: {}').format(resolved.name, exc)) from exc
