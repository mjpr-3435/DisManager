from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Protocol

from ...core.bootstrap.paths import ADDONS_DIR
from ...core.extensions import (
    discover_extension_candidates,
    dispatch_hook,
    ensure_on_sys_path,
    load_extension_module,
    purge_modules_under,
    unload_extensions,
)

if TYPE_CHECKING:
    from ...core.processes import ManagedProcess
    from .client import DisManagerClient


class AddonProtocol(Protocol):
    """Duck-typed lifecycle and process-event contract for DisManager addons."""

    def unload(self) -> object: ...
    async def on_addons_load(self) -> object: ...
    async def on_addons_unload(self) -> object: ...
    async def on_plugins_load(self, process: ManagedProcess) -> object: ...
    async def on_plugins_unload(self, process: ManagedProcess) -> object: ...
    async def on_process_start(self, process: ManagedProcess) -> object: ...
    async def on_process_stop(self, process: ManagedProcess) -> object: ...
    async def on_process_crash(self, process: ManagedProcess) -> object: ...


class AddonManager:
    """Loads, unloads, hot-reloads, and dispatches DisManager events to addons."""

    def __init__(self, client: DisManagerClient) -> None:
        self._client = client
        self._addons: dict[str, object] = {}

    async def load_addons(self, *, reload: bool) -> int:
        """Discover and load addons from ``.addons/``, purging stale modules on reload."""
        if reload:
            await self.unload_addons()

        addons_root = ADDONS_DIR.resolve()
        addons_root.mkdir(parents=True, exist_ok=True)
        ensure_on_sys_path(addons_root)

        if reload:
            purge_modules_under(addons_root)
            importlib.invalidate_caches()

        candidates = discover_extension_candidates(addons_root)
        if not candidates:
            return 0

        if not reload:
            print(self._client._('   • Importing addons:'))

        for addon_name, module_path in candidates:
            try:
                self._addons[addon_name] = load_extension_module(
                    addon_name,
                    module_path,
                    'addon',
                    self._client,
                )
                if not reload:
                    print(self._client._('     -> Imported {}').format(module_path.name))
            except Exception:
                if not reload:
                    print(self._client._('     -> Unable to import {}').format(module_path.name))
                await self._client.report_error(f'AddonImport:{addon_name}')

        await self.call_addons('on_addons_load')
        return len(self._addons)

    async def unload_addons(self) -> None:
        """Invoke ``on_addons_unload`` and ``unload()`` on active addons, then clear them."""
        if not self._addons:
            return

        await self.call_addons('on_addons_unload')
        await unload_extensions(
            self._addons,
            on_error=lambda name: self._client.report_error(f'Addon:{name}.unload'),
        )

    async def call_addons(self, event_name: str, *args: Any) -> None:
        """Dispatch a DisManager lifecycle or process event to addons that implement it."""
        await dispatch_hook(
            self._addons,
            event_name,
            *args,
            on_error=lambda name, hook: self._client.report_error(f'Addon:{name}.{hook}'),
        )
