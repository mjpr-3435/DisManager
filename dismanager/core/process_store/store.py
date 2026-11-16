from __future__ import annotations

import asyncio
import json
import logging
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..bootstrap.paths import DATA_DIR
from .config import ProcessConfig, ProcessConfigError, validate_process_data

_PROCESSES_FILE = DATA_DIR / 'processes.json'
MAX_PROCESSES = 15

_logger = logging.getLogger(__name__)


class ProcessStore:
    """Source of truth for persisted process configurations and their folders on disk."""

    _configs: list[ProcessConfig]

    def __init__(self, store_file: Path = _PROCESSES_FILE) -> None:
        self._store_file = store_file
        self._configs = []

    # --- Internal Behaviour ---

    def _build_config(self, target: str, payload: Mapping[str, Any]) -> ProcessConfig:
        return validate_process_data(
            name=target,
            start_command=payload['start_command'],
            stop_command=payload['stop_command'],
            blacklist=payload['blacklist'],
        )

    def _read_from_disk(self) -> list[ProcessConfig]:
        if not self._store_file.exists():
            return []

        try:
            raw_text = self._store_file.read_text(encoding='utf-8')
            data: object = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            _logger.warning("Resetting unreadable process store '%s': %s", self._store_file, exc)
            self._safe_reset_store()
            return []

        if not isinstance(data, list):
            _logger.warning("Resetting invalid process store '%s': root must be a JSON array.", self._store_file)
            self._safe_reset_store()
            return []

        processes: list[ProcessConfig] = []
        seen_names: set[str] = set()
        needs_repair = False

        for idx, item in enumerate(data):
            try:
                config = self._parse_process_entry(item, index=idx)
            except ProcessConfigError as exc:
                _logger.warning("Discarding invalid entry in '%s': %s", self._store_file, exc)
                needs_repair = True
                continue

            key = config.name.casefold()
            if key in seen_names:
                _logger.warning("Discarding duplicate process '%s' in '%s'.", config.name, self._store_file)
                needs_repair = True
                continue

            seen_names.add(key)
            processes.append(config)

        if len(processes) > MAX_PROCESSES:
            _logger.warning("Purging %d excess process(es) in '%s'.", len(processes) - MAX_PROCESSES, self._store_file)
            processes = processes[:MAX_PROCESSES]
            needs_repair = True

        if needs_repair:
            try:
                self._save_to_disk(processes)
            except ProcessConfigError as exc:
                _logger.warning("Could not save repaired process store '%s': %s", self._store_file, exc)

        return processes

    def _safe_reset_store(self) -> None:
        try:
            self._save_to_disk([])
        except ProcessConfigError as exc:
            _logger.warning("Could not reset process store '%s': %s", self._store_file, exc)

    def _save_to_disk(self, processes: Sequence[ProcessConfig]) -> None:
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
            self._store_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._store_file.with_suffix(f'{self._store_file.suffix}.tmp')
            tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            tmp_path.replace(self._store_file)
        except OSError as exc:
            raise ProcessConfigError(f"Could not save '{self._store_file}': {exc}") from exc

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

        return validate_process_data(
            name=name,
            start_command=start_command,
            stop_command=stop_command,
            blacklist=blacklist,
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

    def get(self, name: str) -> ProcessConfig | None:
        """Return a configured process matching ``name`` case-insensitively."""
        target = name.strip().casefold()
        return next((proc for proc in self._configs if proc.name.casefold() == target), None)

    def create(self, target: str, payload: Mapping[str, Any]) -> ProcessConfig:
        """Validate, persist, and create the working folder for a new process."""
        config = self._build_config(target, payload)
        processes = self._read_from_disk()
        key = config.name.casefold()

        if any(proc.name.casefold() == key for proc in processes):
            raise ProcessConfigError(f"A process named '{config.name}' already exists.")
        if len(processes) >= MAX_PROCESSES:
            raise ProcessConfigError(f'Maximum of {MAX_PROCESSES} processes reached.')

        updated = [*processes, config]
        self._save_to_disk(updated)
        try:
            config.resolve_path().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProcessConfigError(f"Could not create process folder '{config.name}': {exc}") from exc

        self._configs = updated
        return config

    def update(self, target: str, payload: Mapping[str, Any]) -> ProcessConfig:
        """Validate and persist updates to an existing process configuration."""
        config = self._build_config(target, payload)
        processes = self._read_from_disk()
        key = config.name.casefold()
        match_idx = next((idx for idx, proc in enumerate(processes) if proc.name.casefold() == key), None)
        if match_idx is None:
            raise ProcessConfigError(f"Process '{config.name}' was not found.")

        updated = list(processes)
        updated[match_idx] = config
        self._save_to_disk(updated)
        self._configs = updated
        return config

    def delete(self, target: str) -> ProcessConfig:
        """Remove a persisted process by name and return the removed configuration."""
        processes = self._read_from_disk()
        target_key = target.strip().casefold()
        removed = next((proc for proc in processes if proc.name.casefold() == target_key), None)
        if removed is None:
            raise ProcessConfigError(f"Process '{target}' was not found.")

        updated = [proc for proc in processes if proc.name.casefold() != target_key]
        self._save_to_disk(updated)
        self._configs = updated
        return removed

    async def delete_folder(self, name: str) -> None:
        """Safely delete the process working directory if it resides under the workspace root."""
        root = Path.cwd().resolve()
        candidate_dir = (root / name).resolve()
        if candidate_dir == root or not candidate_dir.is_relative_to(root):
            return
        if candidate_dir.exists():
            await asyncio.to_thread(shutil.rmtree, candidate_dir)
