from __future__ import annotations

import asyncio
import importlib
import logging
from typing import TYPE_CHECKING, Any

from ....core.bootstrap.i18n import _
from ....core.bootstrap.paths import ADDONS_DIR
from ....core.extensions import (
    discover_extension_candidates,
    dispatch_hook,
    ensure_on_sys_path,
    load_extension_module,
    purge_modules_under,
    unload_extensions,
)

if TYPE_CHECKING:
    from ..client import DisManagerClient

_logger = logging.getLogger(__name__)


class AddonManager:
    """Loads, unloads, hot-reloads, and dispatches DisManager events to addons."""

    def __init__(self, client: DisManagerClient) -> None:
        self._client = client
        self._addons: dict[str, object] = {}
    
    # --- Internal Behaviour ---

    async def _emit_and_wait(self, event_name: str, *args: Any) -> None:
        await dispatch_hook(
            self._addons,
            event_name,
            *args,
            on_error=lambda name, hook: self._client.report_error(f'Addon:{name}.{hook}'),
        )

        
    # --- Internal API ---

    async def load_addons(self, *, reload: bool) -> int:
        """Discover and load addons from ``.addons/``, purging stale modules on reload."""
        if reload:
            _logger.info('Reloading addons...')
            await self.unload_addons()

        addons_root = ADDONS_DIR.resolve()
        addons_root.mkdir(parents=True, exist_ok=True)
        ensure_on_sys_path(addons_root)

        if reload:
            purge_modules_under(addons_root)
            importlib.invalidate_caches()

        candidates = discover_extension_candidates(addons_root)
        if not candidates:
            if reload:
                _logger.info('No addons found to load.')
            return 0

        if not reload:
            print(_('   • Importing addons:'))

        for addon_name, module_path in candidates:
            try:
                self._addons[addon_name] = load_extension_module(
                    addon_name,
                    module_path,
                    'addon',
                    self._client,
                )
                _logger.info("Loaded addon '%s'.", addon_name)
                if not reload:
                    print(_('     -> Imported {}').format(module_path.name))
            except Exception:
                if not reload:
                    print(_('     -> Unable to import {}').format(module_path.name))
                await self._client.report_error(f'AddonImport:{addon_name}')

        await self._emit_and_wait('on_addons_load')
        count = len(self._addons)
        _logger.info('%s %d addon(s).', 'Reloaded' if reload else 'Loaded', count)
        return count

    async def unload_addons(self) -> None:
        """Invoke ``on_addons_unload`` and ``unload()`` on active addons, then clear them."""
        if not self._addons:
            return

        _logger.info('Unloading %d addon(s): %s', len(self._addons), ', '.join(self._addons))
        await self._emit_and_wait('on_addons_unload')
        await unload_extensions(
            self._addons,
            on_error=lambda name: self._client.report_error(f'Addon:{name}.unload'),
        )

    def emit(self, event_name: str, *args: object) -> None:
        """Schedule an addon event dispatch on the active event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._emit_and_wait(event_name, *args))