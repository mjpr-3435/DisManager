from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ..extensions import (
    discover_extension_candidates,
    dispatch_hook,
    ensure_on_sys_path,
    load_extension_module,
    purge_modules_under,
    unload_extensions,
)

if TYPE_CHECKING:
    from ...discord.client import DisManagerClient
    from .process import ManagedProcess

_NON_IDENT_RE = re.compile(r'[^0-9a-zA-Z_]+')


class PluginProtocol(Protocol):
    """Duck-typed lifecycle and console-event contract for per-process plugins."""

    def unload(self) -> object: ...
    async def on_plugins_load(self) -> object: ...
    async def on_plugins_unload(self) -> object: ...
    async def on_process_start(self) -> object: ...
    async def on_process_stop(self) -> object: ...
    async def on_process_crash(self) -> object: ...
    async def on_process_log(self, log: str) -> object: ...


class PluginManager:
    """Loads, unloads, hot-reloads, and dispatches process events to per-process plugins."""

    def __init__(self, process: ManagedProcess, client: DisManagerClient) -> None:
        self._process = process
        self._client = client
        self._plugins: dict[str, object] = {}

    @property
    def plugins_dir(self) -> Path:
        """Return the ``<process>/.plugins`` directory path."""
        return (self._process.path / '.plugins').resolve()

    async def load_plugins(self, *, reload: bool) -> int:
        """Discover and load plugins from ``<process>/.plugins/``, purging stale modules on reload."""
        if reload:
            await self.unload_plugins()

        root = self.plugins_dir
        root.mkdir(parents=True, exist_ok=True)
        ensure_on_sys_path(root)

        if reload:
            purge_modules_under(root)
            importlib.invalidate_caches()

        candidates = discover_extension_candidates(root)
        if not candidates:
            return 0

        proc_slug = _NON_IDENT_RE.sub('_', self._process.name).strip('_') or 'process'
        for plugin_name, module_path in candidates:
            mod_name = f'_dismanager_plugin_{proc_slug}_{plugin_name}'
            try:
                self._plugins[plugin_name] = load_extension_module(
                    mod_name,
                    module_path,
                    'plugin',
                    self._process,
                )
            except Exception:
                await self._client.report_error(f'PluginImport:{self._process.name}:{plugin_name}')

        await self.call_plugins('on_plugins_load')
        self._client._emit_addon_event('on_plugins_load', self._process)
        return len(self._plugins)

    async def unload_plugins(self) -> None:
        """Invoke ``on_plugins_unload`` and ``unload()`` on active plugins, then clear them."""
        if not self._plugins:
            return

        await self.call_plugins('on_plugins_unload')
        await unload_extensions(
            self._plugins,
            on_error=lambda name: self._client.report_error(f'Plugin:{self._process.name}:{name}.unload'),
        )
        self._client._emit_addon_event('on_plugins_unload', self._process)

    async def call_plugins(self, event_name: str, *args: Any) -> None:
        """Dispatch a lifecycle or console-log event to active plugins of this process."""
        await dispatch_hook(
            self._plugins,
            event_name,
            *args,
            on_error=lambda name, hook: self._client.report_error(
                f'Plugin:{self._process.name}:{name}.{hook}'
            ),
        )
