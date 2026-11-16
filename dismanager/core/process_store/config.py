from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\s\x00-\x1f]')

class ProcessConfigError(Exception):
    """Raised when process configurations cannot be loaded, validated, or saved."""

@dataclass(frozen=True, slots=True)
class ProcessConfig:
    """Persisted configuration for a single managed process."""

    name: str
    start_command: str
    stop_command: str
    blacklist: tuple[str, ...]

    def resolve_path(self) -> Path:
        """Resolve the working directory path automatically from the process name."""
        return Path.cwd().resolve() / self.name


def validate_process_data(
    name: str,
    start_command: str,
    stop_command: str,
    blacklist: Sequence[str] | str,
) -> ProcessConfig:
    """Validate and normalize raw fields into a ``ProcessConfig``."""
    clean_name = name.strip()
    if not clean_name or clean_name in {'.', '..'} or _INVALID_NAME_CHARS.search(clean_name):
        raise ProcessConfigError('Process name must be a valid folder name without spaces.')

    clean_start = start_command.strip()
    clean_stop = stop_command.strip()

    return ProcessConfig(
        name=clean_name,
        start_command=clean_start,
        stop_command=clean_stop,
        blacklist=_normalize_blacklist(blacklist),
    )


def _normalize_blacklist(raw: Sequence[str] | str) -> tuple[str, ...]:
    chunks = raw.splitlines() if isinstance(raw, str) else raw
    result: list[str] = []
    seen: set[str] = set()
    for item in chunks:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return tuple(result)
