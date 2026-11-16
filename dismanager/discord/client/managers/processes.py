from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from ....core.bootstrap.i18n import _
from ....core.managed_process import ManagedProcess
from ....core.process_store import ProcessConfig, ProcessConfigError, ProcessStore

if TYPE_CHECKING:
    from ..client import DisManagerClient


class ProcessManager:
    """Manages runtime ``ManagedProcess`` instances and syncs them with ``ProcessStore``."""

    _processes  : dict[str, ManagedProcess]
    _deleting   : set[str]

    def __init__(self, client: DisManagerClient) -> None:
        self._client    = client
        self._store     = ProcessStore()
        self._processes = {}
        self._deleting  = set()

    # --- Internal Behaviour ---

    def _create_process(self, target: str, payload: Mapping[str, Any]) -> None:
        if target.strip().casefold() in self._deleting:
            raise ProcessConfigError(f"Process '{target.strip()}' is still being deleted. Please wait.")
        
        config = self._store.create(target, payload)
        self._processes[config.name.casefold()] = ManagedProcess(config, self._client)

    def _update_process(self, target: str, payload: Mapping[str, Any]) -> None:
        config = self._store.update(target, payload)
        self._processes[config.name.casefold()].update_config(config)

    def _delete_process(self, target: str, payload: Mapping[str, Any]) -> None:
        removed = self._store.delete(target)
        key = removed.name.casefold()
        process = self._processes.pop(key)
        self._deleting.add(key)
        asyncio.create_task(
            self._cleanup_deleted_process(process, key=key, delete_files=bool(payload['delete_files']))
        )

    async def _cleanup_deleted_process(self, process: ManagedProcess, *, key: str, delete_files: bool) -> None:
        try:
            await process.shutdown()
            if delete_files:
                try:
                    await process.delete_folder()
                except OSError:
                    await self._client.report_error(f'DeleteProcess:{process.name}')
        finally:
            self._deleting.discard(key)

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
        """Shut down all running processes cleanly within timeout and flush store state."""
        if self._processes:
            if any(proc.is_running() for proc in self._processes.values()):
                print(_('Closing processes...'))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(*(proc.shutdown() for proc in self._processes.values()), return_exceptions=True),
                    timeout=65.0,
                )
        try:
            self._store.save()
        except ProcessConfigError:
            await self._client.report_error('ProcessStore.save')
