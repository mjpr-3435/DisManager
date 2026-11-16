from __future__ import annotations

import contextlib
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
