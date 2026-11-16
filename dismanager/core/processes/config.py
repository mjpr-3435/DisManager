from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..bootstrap.paths import DATA_DIR

_PROCESSES_FILE = DATA_DIR / 'processes.json'
MAX_PROCESSES = 15

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\s\x00-\x1f]')
_logger = logging.getLogger(__name__)


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


def load_processes() -> list[ProcessConfig]:
    """Load persisted processes, auto-repairing corrupt, duplicate, or excess entries."""
    if not _PROCESSES_FILE.exists():
        return []

    try:
        raw_text = _PROCESSES_FILE.read_text(encoding='utf-8')
        data: object = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        _logger.warning("Resetting unreadable process store '%s': %s", _PROCESSES_FILE, exc)
        _safe_reset_store()
        return []

    if not isinstance(data, list):
        _logger.warning("Resetting invalid process store '%s': root must be a JSON array.", _PROCESSES_FILE)
        _safe_reset_store()
        return []

    processes: list[ProcessConfig] = []
    seen_names: set[str] = set()
    needs_repair = False

    for idx, item in enumerate(data):
        try:
            config = _parse_process_entry(item, index=idx)
        except ProcessConfigError as exc:
            _logger.warning("Discarding invalid entry in '%s': %s", _PROCESSES_FILE, exc)
            needs_repair = True
            continue

        key = config.name.casefold()
        if key in seen_names:
            _logger.warning("Discarding duplicate process '%s' in '%s'.", config.name, _PROCESSES_FILE)
            needs_repair = True
            continue

        seen_names.add(key)
        processes.append(config)

    if len(processes) > MAX_PROCESSES:
        _logger.warning("Purging %d excess process(es) in '%s'.", len(processes) - MAX_PROCESSES, _PROCESSES_FILE)
        processes = processes[:MAX_PROCESSES]
        needs_repair = True

    if needs_repair:
        try:
            _save_processes(processes)
        except ProcessConfigError as exc:
            _logger.warning("Could not save repaired process store '%s': %s", _PROCESSES_FILE, exc)

    return processes


def _safe_reset_store() -> None:
    try:
        _save_processes([])
    except ProcessConfigError as exc:
        _logger.warning("Could not reset process store '%s': %s", _PROCESSES_FILE, exc)


def _save_processes(processes: Sequence[ProcessConfig]) -> None:
    """Persist process definitions atomically to disk."""
    payload = [
        {
            'name': proc.name,
            'start_command': proc.start_command,
            'stop_command': proc.stop_command,
            'blacklist': list(proc.blacklist),
        }
        for proc in processes
    ]

    try:
        _PROCESSES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _PROCESSES_FILE.with_suffix(f'{_PROCESSES_FILE.suffix}.tmp')
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        tmp_path.replace(_PROCESSES_FILE)
    except OSError as exc:
        raise ProcessConfigError(f"Could not save '{_PROCESSES_FILE}': {exc}") from exc


def upsert_process(config: ProcessConfig, *, is_edit: bool) -> list[ProcessConfig]:
    """Create or update a process definition and persist the updated list."""
    processes = load_processes()
    target_key = config.name.casefold()
    match_idx = next((idx for idx, proc in enumerate(processes) if proc.name.casefold() == target_key), None)

    if not is_edit:
        if match_idx is not None:
            raise ProcessConfigError(f"A process named '{config.name}' already exists.")
        if len(processes) >= MAX_PROCESSES:
            raise ProcessConfigError(f'Maximum of {MAX_PROCESSES} processes reached.')
        updated = [*processes, config]
        _save_processes(updated)
        return updated

    if match_idx is None:
        raise ProcessConfigError(f"Process '{config.name}' was not found.")

    updated = list(processes)
    updated[match_idx] = config
    _save_processes(updated)
    return updated


def delete_process(name: str) -> list[ProcessConfig]:
    """Delete a persisted process by name and save the updated list."""
    processes = load_processes()
    target_key = name.strip().casefold()
    updated = [proc for proc in processes if proc.name.casefold() != target_key]
    if len(updated) == len(processes):
        raise ProcessConfigError(f"Process '{name}' was not found.")

    _save_processes(updated)
    return updated


# =========================================
#            Internal Helpers
# =========================================


def _parse_process_entry(raw: object, *, index: int) -> ProcessConfig:
    if not isinstance(raw, Mapping):
        raise ProcessConfigError(f'Process entry #{index + 1} must be a JSON object.')

    name = raw.get('name')
    start_command = raw.get('start_command')
    stop_command = raw.get('stop_command')
    blacklist = raw.get('blacklist', [])

    if not isinstance(name, str) or not isinstance(start_command, str) or not isinstance(stop_command, str):
        raise ProcessConfigError(
            f"Process entry #{index + 1} requires string 'name', 'start_command', and 'stop_command'."
        )
    if not isinstance(blacklist, list) or not all(isinstance(item, str) for item in blacklist):
        raise ProcessConfigError(f"Process entry #{index + 1} 'blacklist' must be a list of strings.")

    return validate_process_data(
        name=name,
        start_command=start_command,
        stop_command=stop_command,
        blacklist=blacklist,
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
