from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..bootstrap.paths import BACKUPS_DIR

BACKUP_LOG_FILENAME = 'backup_log.txt'
_LOG_PREFIX = 'Backup created on: '


@dataclass(slots=True, frozen=True)
class BackupEntry:
    """Metadata for a single stored process backup."""

    name: str
    path: Path
    created_at: str | None
    size_bytes: int


def process_backups_dir(process_name: str) -> Path:
    """Return the resolved `.backups/<process_name>` directory."""
    return (BACKUPS_DIR / process_name).resolve()


def list_backups(process_name: str) -> list[BackupEntry]:
    """Return existing numbered backups for ``process_name``, ordered 1..N."""
    root = process_backups_dir(process_name)
    if not root.is_dir():
        return []

    indexed: list[tuple[int, Path]] = []
    prefix = f'{process_name} '
    with contextlib.suppress(OSError):
        for entry in root.iterdir():
            if not entry.is_dir() or not entry.name.startswith(prefix):
                continue
            suffix = entry.name.removeprefix(prefix)
            if suffix.isdigit():
                indexed.append((int(suffix), entry))

    indexed.sort(key=lambda item: item[0])
    return [
        BackupEntry(
            name=path.name,
            path=path,
            created_at=_read_backup_timestamp(path / BACKUP_LOG_FILENAME),
            size_bytes=_dir_size_bytes(path),
        )
        for _, path in indexed
    ]


def make_backup(
    process_name: str,
    source_dir: Path,
    max_backups: int,
    progress: list[int] | None = None,
) -> Path:
    """Create a rotating backup ``<process_name> 1`` from ``source_dir``."""
    resolved_source = source_dir.resolve()
    if not resolved_source.is_dir():
        raise FileNotFoundError(f"Process directory '{resolved_source}' does not exist.")

    backups_root = process_backups_dir(process_name)
    backups_root.mkdir(parents=True, exist_ok=True)

    total = _count_files(resolved_source)
    if progress is not None:
        progress[0] = 0
        progress[1] = total

    _rotate_backups(backups_root, process_name, max_backups)

    target_dir = backups_root / f'{process_name} 1'
    _copy_tree_with_progress(resolved_source, target_dir, progress)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    (target_dir / BACKUP_LOG_FILENAME).write_text(f'{_LOG_PREFIX}{timestamp}\n', encoding='utf-8')
    return target_dir


def restore_backup(
    backup_dir: Path,
    target_dir: Path,
    progress: list[int] | None = None,
) -> None:
    """Clear ``target_dir`` contents and restore files from ``backup_dir``."""
    resolved_backup = backup_dir.resolve()
    if not resolved_backup.is_dir():
        raise FileNotFoundError(f"Backup directory '{resolved_backup}' does not exist.")

    total = _count_files(resolved_backup, exclude_name=BACKUP_LOG_FILENAME)
    if progress is not None:
        progress[0] = 0
        progress[1] = total

    resolved_target = target_dir.resolve()
    resolved_target.mkdir(parents=True, exist_ok=True)
    _clear_directory_contents(resolved_target)
    _copy_tree_with_progress(resolved_backup, resolved_target, progress, exclude_name=BACKUP_LOG_FILENAME)


# =========================================
#            Internal Helpers
# =========================================


def _rotate_backups(backups_root: Path, process_name: str, max_backups: int) -> None:
    prefix = f'{process_name} '
    existing: list[tuple[int, Path]] = []
    for entry in backups_root.iterdir():
        if not entry.is_dir() or not entry.name.startswith(prefix):
            continue
        suffix = entry.name.removeprefix(prefix)
        if suffix.isdigit():
            existing.append((int(suffix), entry))

    for idx, path in sorted(existing, key=lambda item: item[0], reverse=True):
        if idx >= max_backups:
            shutil.rmtree(path)
        else:
            path.rename(backups_root / f'{process_name} {idx + 1}')


def _clear_directory_contents(directory: Path) -> None:
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _count_files(directory: Path, *, exclude_name: str | None = None) -> int:
    total = 0
    for root, _, files in os.walk(directory):
        is_root = Path(root) == directory
        for filename in files:
            if is_root and exclude_name is not None and filename == exclude_name:
                continue
            total += 1
    return total


def _copy_tree_with_progress(
    source_dir: Path,
    target_dir: Path,
    progress: list[int] | None,
    *,
    exclude_name: str | None = None,
) -> None:
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
            if progress is not None:
                progress[0] += 1


def _read_backup_timestamp(log_path: Path) -> str | None:
    if not log_path.is_file():
        return None
    with contextlib.suppress(OSError):
        text = log_path.read_text(encoding='utf-8').strip()
        if text.startswith(_LOG_PREFIX):
            return text.removeprefix(_LOG_PREFIX).strip() or None
        return text or None
    return None


def _dir_size_bytes(directory: Path) -> int:
    total = 0
    with contextlib.suppress(OSError):
        for entry in directory.rglob('*'):
            if entry.is_file() and not entry.is_symlink():
                with contextlib.suppress(OSError):
                    total += entry.stat().st_size
    return total
