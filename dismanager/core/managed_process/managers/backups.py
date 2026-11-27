from __future__ import annotations

import contextlib
import logging
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ...bootstrap.paths import BACKUPS_DIR
from ...files import (
    copy_tree_with_progress,
    count_files,
    path_size_bytes,
    remove_path,
)

if TYPE_CHECKING:
    from ..process import ManagedProcess

_logger = logging.getLogger(__name__)

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

    def __init__(self, process: ManagedProcess) -> None:
        self._process = process
        self._operation_lock = threading.Lock()
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    @property
    def backups_dir(self) -> Path:
        """Return the resolved ``.backups/<process_name>`` directory."""
        return (BACKUPS_DIR / self._process.name).resolve()

    def list_backups(self) -> list[BackupEntry]:
        """Return existing numbered backups within ``1..max_backups``, ordered 1..N."""
        indexed = _scan_backups(self.backups_dir, self._process.name, self._process.client.config.backups)
        return [
            BackupEntry(
                name=path.name,
                path=path,
                created_at=_read_backup_timestamp(path / BACKUP_LOG_FILENAME),
                size_bytes=path_size_bytes(path),
            )
            for _, path in indexed
        ]

    def make(self, on_progress: Callable[[int, int], None] | None = None) -> Path:
        """Create a rotating backup ``<process_name> 1`` from the process directory."""
        resolved_source = self._process.path.resolve()
        if not resolved_source.is_dir():
            raise FileNotFoundError(f"Process directory '{resolved_source}' does not exist.")

        backups_root = self.backups_dir
        backups_root.mkdir(parents=True, exist_ok=True)

        total = count_files(resolved_source) if on_progress is not None else 0
        if on_progress is not None:
            on_progress(0, total)

        target_dir = backups_root / f'{self._process.name} 1'
        with self._operation_lock:
            staging = Path(tempfile.mkdtemp(prefix='.backup-', dir=backups_root))
            staged_backup = staging / 'new'
            try:
                copy_tree_with_progress(resolved_source, staged_backup, on_progress, total=total)
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                (staged_backup / BACKUP_LOG_FILENAME).write_text(f'{_LOG_PREFIX}{timestamp}\n', encoding='utf-8')
            except BaseException:
                remove_path(staging)
                raise

            max_backups = self._process.client.config.backups
            indexed = _scan_backups(backups_root, self._process.name, max_backups)
            moves = [(path, staging / f'previous-{idx}') for idx, path in indexed]
            moves.extend(
                (staging / f'previous-{idx}', backups_root / f'{self._process.name} {idx + 1}')
                for idx, _path in indexed
                if idx < max_backups
            )
            moves.append((staged_backup, target_dir))
            _publish_staged(staging, moves)
        _logger.info("[%s] Backup created: '%s'.", self._process.name, target_dir.name)
        return target_dir

    def restore(self, backup_dir: Path, on_progress: Callable[[int, int], None] | None = None) -> None:
        """Stage a backup and replace the process directory, preserving original files on failure."""
        resolved_backup = backup_dir.resolve()
        if not resolved_backup.is_dir():
            raise FileNotFoundError(f"Backup directory '{resolved_backup}' does not exist.")

        total = count_files(resolved_backup, exclude_name=BACKUP_LOG_FILENAME) if on_progress is not None else 0
        if on_progress is not None:
            on_progress(0, total)

        resolved_target = self._process.path.resolve()
        with self._operation_lock:
            resolved_target.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f'.{resolved_target.name}-restore-', dir=resolved_target.parent))
            staged_restore = staging / 'new'
            try:
                copy_tree_with_progress(
                    resolved_backup,
                    staged_restore,
                    on_progress,
                    total=total,
                    exclude_name=BACKUP_LOG_FILENAME,
                )
            except BaseException:
                remove_path(staging)
                raise

            _publish_staged(
                staging,
                [
                    (resolved_target, staging / 'previous-process'),
                    (staged_restore, resolved_target),
                ],
            )
        _logger.info("[%s] Backup restored from '%s'.", self._process.name, resolved_backup.name)


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


def _publish_staged(staging: Path, moves: list[tuple[Path, Path]]) -> None:
    """Publish staged directories, undoing completed renames if publication fails."""
    completed: list[tuple[Path, Path]] = []
    try:
        for source, target in moves:
            source.rename(target)
            completed.append((source, target))
    except BaseException as exc:
        rollback_failed = False
        for source, target in reversed(completed):
            try:
                target.rename(source)
            except OSError:
                rollback_failed = True
                _logger.exception("Could not roll back '%s' to '%s'.", target, source)
        if rollback_failed:
            raise OSError(f"Backup publication and rollback failed. Preserve recovery files in '{staging}'.") from exc
        remove_path(staging)
        raise

    try:
        remove_path(staging)
    except OSError:
        # Publication succeeded; leave old files for manual cleanup if deletion fails.
        _logger.warning("Could not remove completed backup staging directory '%s'.", staging, exc_info=True)


def _read_backup_timestamp(log_path: Path) -> str:
    text = log_path.read_text(encoding='utf-8').strip()
    return text.removeprefix(_LOG_PREFIX).strip()
