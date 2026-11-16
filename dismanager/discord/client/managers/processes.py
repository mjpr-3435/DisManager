from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from ....core.bootstrap.i18n import _
from ....core.managed_process import ManagedProcess
from ....core.process_store import ProcessConfig, ProcessStore

if TYPE_CHECKING:
    from ..client import DisManagerClient


class ProcessManager:
    """Manages runtime ``ManagedProcess`` instances and syncs them with ``ProcessStore``."""

    _processes  : dict[str, ManagedProcess]

    def __init__(self, client: DisManagerClient) -> None:
        self._client    = client
        self._store     = ProcessStore()
        self._processes = {}

    # --- Internal Behaviour ---

    def _create_process(self, target: str, payload: Mapping[str, Any]) -> None:
        config = self._store.create(target, payload)
        self._processes[config.name.casefold()] = ManagedProcess(config, self._client)

    def _update_process(self, target: str, payload: Mapping[str, Any]) -> None:
        config = self._store.update(target, payload)
        self._processes[config.name.casefold()].update_config(config)

    def _delete_process(self, target: str, payload: Mapping[str, Any]) -> None:
        removed = self._store.delete(target)
        process = self._processes.pop(removed.name.casefold())
        asyncio.create_task(
            self._cleanup_deleted_process(process, delete_files=bool(payload['delete_files']))
        )

    async def _cleanup_deleted_process(self, process: ManagedProcess, *, delete_files: bool) -> None:
        await process.shutdown()
        if delete_files:
            try:
                await self._store.delete_folder(process.name)
            except OSError:
                await self._client.report_error(f'DeleteProcess:{process.name}')

    # --- Internal API ---

    @property
    def configs(self) -> tuple[ProcessConfig, ...]:
        """Return a read-only snapshot of persisted process configurations."""
        return self._store.configs

    def list_processes(self) -> list[ManagedProcess]:
        """Return all managed process instances."""
        return list(self._processes.values())

    def get_config(self, name: str) -> ProcessConfig | None:
        """Return a configured process from the store."""
        return self._store.get(name)

    def find(self, name: str) -> ManagedProcess | None:
        """Return a managed process matching ``name`` case-insensitively."""
        return self._processes.get(name.strip().casefold())

    def load(self) -> None:
        """Load process configurations from disk and instantiate managed processes."""
        configs = self._store.load()
        self._processes = {
            proc.name.casefold(): ManagedProcess(proc, self._client) for proc in configs
        }

    def on_edit(
        self,
        event: Literal['new', 'update', 'delete'],
        target: str,
        payload: Mapping[str, Any],
    ) -> None:
        """Persist process changes via the store, update runtime state, and refresh the panel."""
        if event == 'new':
            self._create_process(target, payload)
        elif event == 'update':
            self._update_process(target, payload)
        elif event == 'delete':
            self._delete_process(target, payload)
        else:
            raise ValueError(f'Unsupported process edit event: {event}')

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
