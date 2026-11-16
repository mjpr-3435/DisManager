from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from ....core.bootstrap.i18n import _
from ....core.processes import (
    ManagedProcess,
    ProcessConfig,
    ProcessConfigError,
    ProcessDeleteRequest,
    delete_process,
    load_processes,
    upsert_process,
)

if TYPE_CHECKING:
    from ..client import DisManagerClient


class ProcessManager:
    """Manages configured processes, CRUD updates, plugin reloads, and shutdown."""

    configs     : list[ProcessConfig]
    _processes  : dict[str, ManagedProcess]

    def __init__(self, client: DisManagerClient) -> None:
        self._client    = client
        self._processes = {}
        self.configs    = []

    # --- Internal Behaviour ---

    async def _cleanup_deleted_process(
        self,
        process: ManagedProcess | None,
        target_dir: Path | None,
    ) -> None:
        if process is not None:
            await process.shutdown()
        if target_dir is not None and target_dir.exists():
            try:
                await asyncio.to_thread(shutil.rmtree, target_dir)
            except OSError:
                await self._client.report_error(f'DeleteProcess:{target_dir.name}')

    # --- Internal API ---

    def list_processes(self) -> list[ManagedProcess]:
        """Return all managed process instances."""
        return list(self._processes.values())

    def get_config(self, name: str) -> ProcessConfig | None:
        """Return a configured process from in-memory state."""
        target = name.strip().casefold()
        return next((proc for proc in self.configs if proc.name.casefold() == target), None)

    def find(self, name: str) -> ManagedProcess | None:
        """Return a managed process matching ``name`` case-insensitively."""
        return self._processes.get(name.strip().casefold())

    def load(self) -> None:
        """Load process configurations and instantiate managed processes."""
        self.configs = load_processes()
        self._processes = {
            proc.name.casefold(): ManagedProcess(proc, self._client) for proc in self.configs
        }

    def create(self, config: ProcessConfig) -> None:
        """Persist a new process, instantiate it, create its folder, and refresh the panel."""
        self.configs = upsert_process(config, is_edit=False)
        self._processes[config.name.casefold()] = ManagedProcess(config, self._client)
        try:
            config.resolve_path().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProcessConfigError(f"Could not create process folder '{config.name}': {exc}") from exc
        self._client._panel_manager.refresh()

    def update(self, config: ProcessConfig) -> None:
        """Persist process updates, apply them in memory, and refresh the panel."""
        self.configs = upsert_process(config, is_edit=True)
        process = self._processes.get(config.name.casefold())
        if process is not None:
            process.update_config(config)
        self._client._panel_manager.refresh()

    def delete(self, request: ProcessDeleteRequest) -> None:
        """Remove a process from config and memory, optionally delete its folder, and refresh the panel."""
        target_proc = self.get_config(request.name)
        self.configs = delete_process(request.name)
        process = self._processes.pop(request.name.casefold(), None)
        target_dir: Path | None = None
        if request.delete_files and target_proc is not None:
            root = Path.cwd().resolve()
            candidate_dir = target_proc.resolve_path().resolve()
            if candidate_dir != root and candidate_dir.is_relative_to(root):
                target_dir = candidate_dir
        if process is not None or target_dir is not None:
            asyncio.create_task(self._cleanup_deleted_process(process, target_dir))
        self._client._panel_manager.refresh()

    async def shutdown_all(self) -> None:
        """Shut down all running processes cleanly within timeout."""
        if not self._processes:
            return
        if any(proc.is_running() for proc in self._processes.values()):
            print(_('Closing processes...'))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(*(proc.shutdown() for proc in self._processes.values()), return_exceptions=True),
                timeout=65.0,
            )