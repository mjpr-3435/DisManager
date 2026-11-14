from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .paths import DATA_DIR

PROCESSES_FILE = DATA_DIR / 'processes.json'
MAX_PROCESSES = 15

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ProcessConfigError(Exception):
    """Raised when process configurations cannot be loaded, validated, or saved."""


@dataclass(frozen=True, slots=True)
class ProcessConfig:
    """Persisted configuration for a single managed process."""

    name: str
    start_command: str
    stop_command: str
    blacklist: tuple[str, ...] = ()

    def resolve_path(self, root: Path | None = None) -> Path:
        """Resolve the working directory path automatically from the process name."""
        base = (root or Path.cwd()).resolve()
        return base / self.name


def validate_process_data(
    name: str,
    start_command: str,
    stop_command: str,
    blacklist: Sequence[str] | str = (),
) -> ProcessConfig:
    """Validate and normalize raw fields into a ``ProcessConfig``."""
    clean_name = name.strip()
    if not clean_name or clean_name in {'.', '..'} or _INVALID_NAME_CHARS.search(clean_name):
        raise ProcessConfigError('Process name must be a valid folder name.')

    clean_start = start_command.strip()
    clean_stop = stop_command.strip()

    return ProcessConfig(
        name=clean_name,
        start_command=clean_start,
        stop_command=clean_stop,
        blacklist=_normalize_blacklist(blacklist),
    )


def load_processes(path: str | Path = PROCESSES_FILE) -> list[ProcessConfig]:
    """Load and validate all persisted process definitions from disk."""
    file_path = Path(path)
    if not file_path.exists():
        return []

    try:
        raw_text = file_path.read_text(encoding='utf-8')
    except OSError as exc:
        raise ProcessConfigError(f"Could not read '{file_path}': {exc}") from exc

    try:
        data: object = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProcessConfigError(f"Invalid JSON in '{file_path}': {exc}") from exc

    if not isinstance(data, list):
        raise ProcessConfigError(f"Process store '{file_path}' must contain a JSON array.")

    processes: list[ProcessConfig] = []
    seen_names: set[str] = set()
    for idx, item in enumerate(data):
        config = _parse_process_entry(item, index=idx)
        key = config.name.casefold()
        if key in seen_names:
            raise ProcessConfigError(f"Duplicate process name '{config.name}' in '{file_path}'.")
        seen_names.add(key)
        processes.append(config)

    return processes


def save_processes(processes: Sequence[ProcessConfig], path: str | Path = PROCESSES_FILE) -> None:
    """Persist process definitions atomically to disk."""
    file_path = Path(path)
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
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(f'{file_path.suffix}.tmp')
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        tmp_path.replace(file_path)
    except OSError as exc:
        raise ProcessConfigError(f"Could not save '{file_path}': {exc}") from exc


def get_process(name: str, path: str | Path = PROCESSES_FILE) -> ProcessConfig | None:
    """Return a persisted process by name (case-insensitive), or ``None``."""
    target = name.strip().casefold()
    for proc in load_processes(path):
        if proc.name.casefold() == target:
            return proc
    return None


def upsert_process(
    config: ProcessConfig,
    *,
    is_edit: bool = False,
    path: str | Path = PROCESSES_FILE,
) -> list[ProcessConfig]:
    """Create or update a process definition and persist the updated list."""
    processes = load_processes(path)
    target_key = config.name.casefold()
    match_idx = next((idx for idx, proc in enumerate(processes) if proc.name.casefold() == target_key), None)

    if not is_edit:
        if match_idx is not None:
            raise ProcessConfigError(f"A process named '{config.name}' already exists.")
        if len(processes) >= MAX_PROCESSES:
            raise ProcessConfigError(f'Maximum of {MAX_PROCESSES} processes reached.')
        updated = [*processes, config]
        save_processes(updated, path)
        return updated

    if match_idx is None:
        raise ProcessConfigError(f"Process '{config.name}' was not found.")

    updated = list(processes)
    updated[match_idx] = config
    save_processes(updated, path)
    return updated


def delete_process(name: str, path: str | Path = PROCESSES_FILE) -> list[ProcessConfig]:
    """Delete a persisted process by name and save the updated list."""
    processes = load_processes(path)
    target_key = name.strip().casefold()
    updated = [proc for proc in processes if proc.name.casefold() != target_key]
    if len(updated) == len(processes):
        raise ProcessConfigError(f"Process '{name}' was not found.")

    save_processes(updated, path)
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
