from __future__ import annotations

from pathlib import Path

DATA_DIR = Path('.dismanager')
LOGS_DIR = DATA_DIR / 'logs'
_BACKUPS_DIR = Path('.backups')
ADDONS_DIR = Path('.addons')


def ensure_workspace_dirs() -> None:
    """Create the runtime workspace directories if they do not exist."""
    for directory in (DATA_DIR, LOGS_DIR, _BACKUPS_DIR, ADDONS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
