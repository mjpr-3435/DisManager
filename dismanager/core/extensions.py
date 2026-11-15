from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any


def ensure_on_sys_path(root: Path) -> None:
    """Insert ``root`` at the front of ``sys.path`` if not already present."""
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def discover_extension_candidates(root: Path) -> list[tuple[str, Path]]:
    """Return sorted ``(name, entry_path)`` pairs for ``.py`` files and packages under ``root``."""
    candidates: list[tuple[str, Path]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if entry.name.startswith('.') or entry.name == '__pycache__':
            continue
        if entry.is_file() and entry.suffix == '.py':
            candidates.append((entry.stem, entry))
        elif entry.is_dir():
            init_file = entry / '__init__.py'
            if init_file.is_file():
                candidates.append((entry.name, init_file))
    return candidates


def purge_modules_under(root: Path) -> None:
    """Remove any loaded ``sys.modules`` entries whose source file resides under ``root``."""
    for mod_name, module in list(sys.modules.items()):
        mod_file = getattr(module, '__file__', None)
        if not isinstance(mod_file, str):
            continue
        try:
            resolved = Path(mod_file).resolve()
        except OSError:
            continue
        if resolved.is_relative_to(root):
            sys.modules.pop(mod_name, None)


def load_extension_module(
    module_name: str,
    module_path: Path,
    factory_attr: str,
    target: Any,
) -> object:
    """Import ``module_path`` as ``module_name`` and instantiate ``getattr(module, factory_attr)(target)``."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for '{module_path}'.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        factory = getattr(module, factory_attr)
        if not callable(factory):
            raise TypeError(f"'{module_name}.{factory_attr}' must be callable.")
        return factory(target)
    except Exception:
        sys.modules.pop(module_name, None)
        raise


async def dispatch_hook(
    extensions: Mapping[str, object],
    hook_name: str,
    *args: Any,
    on_error: Callable[[str, str], Awaitable[None]],
) -> None:
    """Invoke ``hook_name(*args)`` on each extension that defines it."""
    for ext_name, extension in list(extensions.items()):
        hook = getattr(extension, hook_name, None)
        if not callable(hook):
            continue
        try:
            result = hook(*args)
            if inspect.isawaitable(result):
                await result
        except Exception:
            await on_error(ext_name, hook_name)


async def unload_extensions(
    extensions: dict[str, object],
    *,
    on_error: Callable[[str], Awaitable[None]],
) -> None:
    """Invoke ``unload()`` on each extension and clear ``extensions``."""
    for ext_name, extension in list(extensions.items()):
        unload = getattr(extension, 'unload', None)
        if not callable(unload):
            continue
        try:
            result = unload()
            if inspect.isawaitable(result):
                await result
        except Exception:
            await on_error(ext_name)
    extensions.clear()
