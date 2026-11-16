from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ...bootstrap.paths import BACKUPS_DIR
from ...utils import dir_size_bytes

if TYPE_CHECKING:
    from ...bootstrap.config import DisManagerConfig
    from ...process_store import ProcessConfig

BACKUP_LOG_FILENAME = 'backup_log.txt'
_LOG_PREFIX = 'Backup created on: '


@dataclass(slots=True, frozen=True)
class BackupEntry:
    """Metadata for a single stored process backup."""

    name: str
    path: Path
    created_at: str
    size_bytes: int


class BackupManager:
    """Manages rotating backups under ``.backups/<process_name>``."""

    def __init__(self, config: ProcessConfig, app_config: DisManagerConfig) -> None:
        self._config = config
        self._app_config = app_config
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    @property
    def backups_dir(self) -> Path:
        """Return the resolved ``.backups/<process_name>`` directory."""
        return (BACKUPS_DIR / self._config.name).resolve()

    def list_backups(self) -> list[BackupEntry]:
        """Return existing numbered backups within ``1..max_backups``, ordered 1..N."""
        indexed = _scan_backups(self.backups_dir, self._config.name, self._app_config.backups)
        return [
            BackupEntry(
                name=path.name,
                path=path,
                created_at=_read_backup_timestamp(path / BACKUP_LOG_FILENAME),
                size_bytes=dir_size_bytes(path),
            )
            for _, path in indexed
        ]

    def make(self, progress: list[int] | None = None) -> Path:
        """Create a rotating backup ``<process_name> 1`` from the process directory."""
        resolved_source = self._config.resolve_path().resolve()
        if not resolved_source.is_dir():
            raise FileNotFoundError(f"Process directory '{resolved_source}' does not exist.")

        backups_root = self.backups_dir
        backups_root.mkdir(parents=True, exist_ok=True)

        total = _count_files(resolved_source)
        if progress is not None:
            progress[0] = 0
            progress[1] = total

        _rotate_backups(backups_root, self._config.name, self._app_config.backups)

        target_dir = backups_root / f'{self._config.name} 1'
        _remove_path(target_dir)
        _copy_tree_with_progress(resolved_source, target_dir, progress)

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        (target_dir / BACKUP_LOG_FILENAME).write_text(f'{_LOG_PREFIX}{timestamp}\n', encoding='utf-8')
        return target_dir

    def restore(self, backup_dir: Path, progress: list[int] | None = None) -> None:
        """Clear the process directory contents and restore files from ``backup_dir``."""
        resolved_backup = backup_dir.resolve()
        if not resolved_backup.is_dir():
            raise FileNotFoundError(f"Backup directory '{resolved_backup}' does not exist.")

        total = _count_files(resolved_backup, exclude_name=BACKUP_LOG_FILENAME)
        if progress is not None:
            progress[0] = 0
            progress[1] = total

        resolved_target = self._config.resolve_path().resolve()
        resolved_target.mkdir(parents=True, exist_ok=True)
        _clear_directory_contents(resolved_target)
        _copy_tree_with_progress(resolved_backup, resolved_target, progress, exclude_name=BACKUP_LOG_FILENAME)


# =========================================
#            Internal Helpers
# =========================================


def _scan_backups(backups_root: Path, process_name: str, max_backups: int) -> list[tuple[int, Path]]:
    prefix = f'{process_name} '
    indexed: list[tuple[int, Path]] = []
    with contextlib.suppress(OSError):
        for entry in backups_root.iterdir():
            if not entry.is_dir() or not entry.name.startswith(prefix):
                continue
            suffix = entry.name.removeprefix(prefix)
            if not suffix.isdigit():
                continue
            idx = int(suffix)
            if 1 <= idx <= max_backups and (entry / BACKUP_LOG_FILENAME).is_file():
                indexed.append((idx, entry))
    indexed.sort(key=lambda item: item[0])
    return indexed


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _rotate_backups(backups_root: Path, process_name: str, max_backups: int) -> None:
    for idx, path in reversed(_scan_backups(backups_root, process_name, max_backups)):
        if idx >= max_backups:
            _remove_path(path)
        else:
            dest = backups_root / f'{process_name} {idx + 1}'
            _remove_path(dest)
            path.rename(dest)


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


def _read_backup_timestamp(log_path: Path) -> str:
    text = log_path.read_text(encoding='utf-8').strip()
    return text.removeprefix(_LOG_PREFIX).strip()
