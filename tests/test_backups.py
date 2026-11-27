from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from dismanager.core.files import copy_tree_with_progress
from dismanager.core.managed_process import ManagedProcess
from dismanager.core.managed_process.managers import backups


class BackupSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'server'
        self.source.mkdir()
        (self.source / 'live.txt').write_text('original', encoding='utf-8')
        self.config = SimpleNamespace(backups=1)
        process = SimpleNamespace(name='server', path=self.source, client=SimpleNamespace(config=self.config))
        self.paths = patch.object(backups, 'BACKUPS_DIR', self.root / 'backups')
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.manager = backups.BackupManager(cast(ManagedProcess, process))

    def snapshot(self, directory: Path) -> dict[str, bytes]:
        return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob('*') if path.is_file()}

    def fail_copy(self, source: Path, target: Path, *args: object, **kwargs: object) -> None:
        target.mkdir(parents=True, exist_ok=True)
        (target / 'partial.txt').write_text('partial', encoding='utf-8')
        raise OSError('disk full')

    def test_failed_backup_keeps_existing_backups(self) -> None:
        for retention in (1, 3):
            with self.subTest(retention=retention):
                self.config.backups = retention
                for _ in range(retention):
                    self.manager.make()
                before = self.snapshot(self.manager.backups_dir)
                with (
                    patch.object(backups, 'copy_tree_with_progress', side_effect=self.fail_copy),
                    self.assertRaisesRegex(OSError, 'disk full'),
                ):
                    self.manager.make()
                self.assertEqual(self.snapshot(self.manager.backups_dir), before)
                self.assertFalse(list(self.manager.backups_dir.glob('.backup-*')))

    def test_failed_restore_keeps_current_files_and_backup(self) -> None:
        backup = self.manager.make()
        (self.source / 'live.txt').write_text('newer data', encoding='utf-8')
        current = self.snapshot(self.source)
        saved = self.snapshot(backup)
        with (
            patch.object(backups, 'copy_tree_with_progress', side_effect=self.fail_copy),
            self.assertRaisesRegex(OSError, 'disk full'),
        ):
            self.manager.restore(backup)
        self.assertEqual(self.snapshot(self.source), current)
        self.assertEqual(self.snapshot(backup), saved)
        self.assertFalse(list(self.root.glob('.server-restore-*')))

    def test_metadata_failure_keeps_previous_backup(self) -> None:
        self.manager.make()
        before = self.snapshot(self.manager.backups_dir)
        with (
            patch.object(Path, 'write_text', side_effect=OSError('metadata write failed')),
            self.assertRaisesRegex(OSError, 'metadata write failed'),
        ):
            self.manager.make()
        self.assertEqual(self.snapshot(self.manager.backups_dir), before)

    def test_successful_backup_rotates_and_restore_replaces_files(self) -> None:
        self.config.backups = 2
        self.manager.make()
        (self.source / 'live.txt').write_text('second', encoding='utf-8')
        self.manager.make()
        (self.source / 'live.txt').write_text('third', encoding='utf-8')
        latest = self.manager.make()
        entries = self.manager.list_backups()
        self.assertEqual([entry.name for entry in entries], ['server 1', 'server 2'])
        self.assertEqual((entries[1].path / 'live.txt').read_text(encoding='utf-8'), 'second')
        self.assertEqual(list(self.manager.backups_dir.glob('.backup-*')), [])
        before = self.snapshot(latest)
        (self.source / 'extra.txt').write_text('not in backup', encoding='utf-8')
        self.manager.restore(latest)
        self.assertEqual(self.snapshot(self.source), {'live.txt': b'third'})
        self.assertEqual(self.snapshot(latest), before)
        self.assertFalse(list(self.root.glob('.server-restore-*')))

    def test_backup_publication_failure_rolls_back_every_rename(self) -> None:
        self.config.backups = 3
        for _ in range(3):
            self.manager.make()
        before = self.snapshot(self.manager.backups_dir)
        rename = Path.rename
        for failure_at in range(1, 7):
            with self.subTest(failure_at=failure_at):
                calls = 0

                def fail_rename(path: Path, target: Path, failure_at: int = failure_at) -> Path:
                    nonlocal calls
                    calls += 1
                    if calls == failure_at:
                        raise OSError('rename failed')
                    return rename(path, target)

                with patch.object(Path, 'rename', fail_rename), self.assertRaisesRegex(OSError, 'rename failed'):
                    self.manager.make()
                self.assertEqual(self.snapshot(self.manager.backups_dir), before)
                self.assertFalse(list(self.manager.backups_dir.glob('.backup-*')))

    def test_restore_publication_failure_rolls_back(self) -> None:
        backup = self.manager.make()
        (self.source / 'live.txt').write_text('newer data', encoding='utf-8')
        rename = Path.rename
        for failure_at in (1, 2):
            with self.subTest(failure_at=failure_at):
                calls = 0

                def fail_rename(path: Path, target: Path, failure_at: int = failure_at) -> Path:
                    nonlocal calls
                    calls += 1
                    if calls == failure_at:
                        raise OSError('rename failed')
                    return rename(path, target)

                with patch.object(Path, 'rename', fail_rename), self.assertRaisesRegex(OSError, 'rename failed'):
                    self.manager.restore(backup)
                self.assertEqual(self.snapshot(self.source), {'live.txt': b'newer data'})
                self.assertFalse(list(self.root.glob('.server-restore-*')))

    def test_failed_rollback_preserves_recovery_directory(self) -> None:
        backup = self.manager.make()
        (self.source / 'live.txt').write_text('newer data', encoding='utf-8')
        rename = Path.rename
        calls = 0

        def fail_rename(path: Path, target: Path) -> Path:
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise OSError('filesystem unavailable')
            return rename(path, target)

        with (
            patch.object(Path, 'rename', fail_rename),
            self.assertLogs(backups._logger, level='ERROR'),
            self.assertRaisesRegex(OSError, 'Preserve recovery files') as raised,
        ):
            self.manager.restore(backup)
        recovery = next(self.root.glob('.server-restore-*'))
        self.assertIn(str(recovery), str(raised.exception))
        self.assertEqual(self.snapshot(recovery / 'previous-process'), {'live.txt': b'newer data'})
        self.assertEqual((backup / 'live.txt').read_text(encoding='utf-8'), 'original')

    def test_unreadable_directory_aborts_copy(self) -> None:
        with (
            patch('os.scandir', side_effect=PermissionError('cannot read directory')),
            self.assertRaisesRegex(PermissionError, 'cannot read directory'),
        ):
            copy_tree_with_progress(self.source, self.root / 'copy')


if __name__ == '__main__':
    unittest.main()
