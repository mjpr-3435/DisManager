from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from ..bootstrap.paths import DATA_DIR
from .config import ProcessConfig, ProcessConfigError

_PROCESSES_FILE = DATA_DIR / 'processes.json'
MAX_PROCESSES = 15

_VALID_NAME_RE = re.compile(r'[A-Za-z0-9]+')
_logger = logging.getLogger(__name__)


class ProcessStore:
    """Source of truth for persisted process configurations and their folders on disk."""

    _configs: list[ProcessConfig]

    def __init__(self) -> None:
        self._configs = []

    # --- Internal Behaviour ---

    def _commit(self, processes: list[ProcessConfig]) -> None:
        """Persist process definitions atomically to disk."""
        payload = [asdict(proc) for proc in processes]

        try:
            _PROCESSES_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = _PROCESSES_FILE.with_suffix(f'{_PROCESSES_FILE.suffix}.tmp')
            tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            tmp_path.replace(_PROCESSES_FILE)
        except OSError as exc:
            raise ProcessConfigError(f"Could not save '{_PROCESSES_FILE}': {exc}") from exc

        self._configs = processes

    def _safe_reset_store(self) -> None:
        try:
            self._commit([])
        except ProcessConfigError as exc:
            _logger.warning("Could not reset process store '%s': %s", _PROCESSES_FILE, exc)

    def _read_from_disk(self) -> list[ProcessConfig]:
        if not _PROCESSES_FILE.exists():
            return []

        try:
            raw_text = _PROCESSES_FILE.read_text(encoding='utf-8')
            data: object = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            _logger.warning("Resetting unreadable process store '%s': %s", _PROCESSES_FILE, exc)
            self._safe_reset_store()
            return []

        if not isinstance(data, list):
            _logger.warning("Resetting invalid process store '%s': root must be a JSON array.", _PROCESSES_FILE)
            self._safe_reset_store()
            return []

        processes: list[ProcessConfig] = []
        seen_names: set[str] = set()
        needs_repair = False

        for idx, item in enumerate(data):
            try:
                config = self._parse_process_entry(item, index=idx)
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
                self._commit(processes)
            except ProcessConfigError as exc:
                _logger.warning("Could not save repaired process store '%s': %s", _PROCESSES_FILE, exc)

        return processes
    
    def _parse_process_entry(self, raw: object, *, index: int) -> ProcessConfig:
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

        return self._validate_process_data(
            name=name,
            start_command=start_command,
            stop_command=stop_command,
            blacklist=blacklist,
        )

    def _validate_process_data(
        self,
        *,
        name: str,
        start_command: str,
        stop_command: str,
        blacklist: Sequence[str],
    ) -> ProcessConfig:
        clean_name = name.strip()
        if not _VALID_NAME_RE.fullmatch(clean_name):
            raise ProcessConfigError('Process name must contain only letters and numbers.')

        return ProcessConfig(
            name=clean_name,
            start_command=start_command.strip(),
            stop_command=stop_command.strip(),
            blacklist=self._normalize_blacklist(blacklist),
        )

    def _normalize_blacklist(self, raw: Sequence[str]) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        for item in raw:
            # Trim surrounding whitespace and skip empty or duplicate lines (preserving order).
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return tuple(result)

    def _build_config(self, target: str, payload: Mapping[str, Any]) -> ProcessConfig:
        return self._validate_process_data(
            name=target,
            start_command=payload['start_command'],
            stop_command=payload['stop_command'],
            blacklist=payload['blacklist'],
        )

    # --- Internal API ---

    @property
    def configs(self) -> tuple[ProcessConfig, ...]:
        """Return a read-only snapshot of loaded process configurations."""
        return tuple(self._configs)
    
    def load(self) -> tuple[ProcessConfig, ...]:
        """Load persisted processes, auto-repairing corrupt, duplicate, or excess entries."""
        self._configs = self._read_from_disk()
        return tuple(self._configs)

    def save(self) -> None:
        """Persist the current in-memory process configurations to disk."""
        self._commit(self._configs)

    def get(self, name: str) -> ProcessConfig | None:
        """Return a configured process matching ``name`` case-insensitively."""
        target = name.strip().casefold()
        return next((proc for proc in self._configs if proc.name.casefold() == target), None)

    def create(self, target: str, payload: Mapping[str, Any]) -> ProcessConfig:
        """Validate, persist, and create the working folder for a new process."""
        config = self._build_config(target, payload)
        key = config.name.casefold()

        if any(proc.name.casefold() == key for proc in self._configs):
            raise ProcessConfigError(f"A process named '{config.name}' already exists.")
        if len(self._configs) >= MAX_PROCESSES:
            raise ProcessConfigError(f'Maximum of {MAX_PROCESSES} processes reached.')

        updated = [*self._configs, config]
        self._commit(updated)
        return config

    def update(self, target: str, payload: Mapping[str, Any]) -> ProcessConfig:
        """Validate and persist updates to an existing process configuration."""
        config = self._build_config(target, payload)
        key = config.name.casefold()
        match_idx = next((idx for idx, proc in enumerate(self._configs) if proc.name.casefold() == key), None)
        if match_idx is None:
            raise ProcessConfigError(f"Process '{config.name}' was not found.")

        updated = self._configs.copy()
        updated[match_idx] = config
        self._commit(updated)
        return config

    def delete(self, target: str) -> ProcessConfig:
        """Remove a persisted process by name and return the removed configuration."""
        target_key = target.strip().casefold()
        removed = next((proc for proc in self._configs if proc.name.casefold() == target_key), None)
        if removed is None:
            raise ProcessConfigError(f"Process '{target}' was not found.")

        updated = [proc for proc in self._configs if proc.name.casefold() != target_key]
        self._commit(updated)
        return removed
