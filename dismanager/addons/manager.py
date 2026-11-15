from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ..core.paths import ADDONS_DIR

if TYPE_CHECKING:
    from ..discord.client import DisManagerClient
    from ..processes import ManagedProcess


class AddonProtocol(Protocol):
    """Duck-typed lifecycle and process-event contract for DisManager addons."""

    def unload(self) -> object: ...
    async def on_addons_load(self, client: DisManagerClient) -> object: ...
    async def on_addons_unload(self, client: DisManagerClient) -> object: ...
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
        self._ensure_on_sys_path(addons_root)

        if reload:
            self._purge_addon_modules(addons_root)
            importlib.invalidate_caches()

        candidates = self._discover_candidates(addons_root)
        if not candidates:
            return 0

        if not reload:
            print(self._client._('   • Importing addons:'))

        for addon_name, module_path in candidates:
            try:
                spec = importlib.util.spec_from_file_location(addon_name, module_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Could not create module spec for '{module_path}'.")

                module = importlib.util.module_from_spec(spec)
                sys.modules[addon_name] = module
                try:
                    spec.loader.exec_module(module)
                    factory = module.addon
                    if not callable(factory):
                        raise TypeError(f"'{addon_name}.addon' must be callable.")
                    self._addons[addon_name] = factory(self._client)
                except Exception:
                    sys.modules.pop(addon_name, None)
                    raise

                if not reload:
                    print(self._client._('     -> Imported {}').format(module_path.name))
            except Exception:
                if not reload:
                    print(self._client._('     -> Unable to import {}').format(module_path.name))
                await self._client.report_error(f'AddonImport:{addon_name}')

        await self.call_addons('on_addons_load', self._client)
        return len(self._addons)

    async def unload_addons(self) -> None:
        """Invoke ``on_addons_unload`` and ``unload()`` on active addons, then clear them."""
        if not self._addons:
            return

        await self.call_addons('on_addons_unload', self._client)

        for addon_name, addon in list(self._addons.items()):
            unload = getattr(addon, 'unload', None)
            if not callable(unload):
                continue
            try:
                result = unload()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                await self._client.report_error(f'Addon:{addon_name}.unload')

        self._addons.clear()

    async def call_addons(self, event_name: str, *args: Any) -> None:
        """Dispatch a DisManager lifecycle or process event to addons that implement it."""
        for addon_name, addon in list(self._addons.items()):
            hook = getattr(addon, event_name, None)
            if not callable(hook):
                continue
            try:
                result = hook(*args)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                await self._client.report_error(f'Addon:{addon_name}.{event_name}')

    # =========================================
    #            Internal Helpers
    # =========================================

    def _ensure_on_sys_path(self, addons_root: Path) -> None:
        root_str = str(addons_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    def _discover_candidates(self, addons_root: Path) -> list[tuple[str, Path]]:
        candidates: list[tuple[str, Path]] = []
        for entry in sorted(addons_root.iterdir(), key=lambda item: item.name.casefold()):
            if entry.name.startswith('.') or entry.name == '__pycache__':
                continue
            if entry.is_file() and entry.suffix == '.py':
                candidates.append((entry.stem, entry))
            elif entry.is_dir():
                init_file = entry / '__init__.py'
                if init_file.is_file():
                    candidates.append((entry.name, init_file))
        return candidates

    def _purge_addon_modules(self, addons_root: Path) -> None:
        for mod_name, module in list(sys.modules.items()):
            mod_file = getattr(module, '__file__', None)
            if not isinstance(mod_file, str):
                continue
            try:
                resolved = Path(mod_file).resolve()
            except OSError:
                continue
            if resolved.is_relative_to(addons_root):
                sys.modules.pop(mod_name, None)
