from __future__ import annotations

from .core.managed_process import ManagedProcess
from .discord.client import DisManagerClient


class BaseAddon:
    """Optional base class providing typed hook signatures for DisManager addons."""

    def unload(self) -> object:
        """Called when the addon is unloaded or reloaded."""
        return None

    async def on_addons_load(self) -> object:
        """Called after all addons have been imported."""
        return None

    async def on_addons_unload(self) -> object:
        """Called before addons are unloaded."""
        return None

    async def on_plugins_load(self, process: ManagedProcess) -> object:
        """Called when a process finishes loading its plugins."""
        return None

    async def on_plugins_unload(self, process: ManagedProcess) -> object:
        """Called before a process unloads its plugins."""
        return None

    async def on_process_start(self, process: ManagedProcess) -> object:
        """Called when a managed process starts."""
        return None

    async def on_process_stop(self, process: ManagedProcess) -> object:
        """Called when a managed process is requested to stop or kill."""
        return None

    async def on_process_crash(self, process: ManagedProcess) -> object:
        """Called when a managed process exits unexpectedly with a non-zero code."""
        return None


class BasePlugin:
    """Optional base class providing typed hook signatures for per-process plugins."""

    def unload(self) -> object:
        """Called when the plugin is unloaded or reloaded."""
        return None

    async def on_plugins_load(self) -> object:
        """Called after this process's plugins have been imported."""
        return None

    async def on_plugins_unload(self) -> object:
        """Called before this process's plugins are unloaded."""
        return None

    async def on_process_start(self) -> object:
        """Called when the owning process starts."""
        return None

    async def on_process_stop(self) -> object:
        """Called when the owning process is requested to stop or kill."""
        return None

    async def on_process_crash(self) -> object:
        """Called when the owning process exits unexpectedly with a non-zero code."""
        return None

    async def on_process_log(self, log: str) -> object:
        """Called for each filtered console output line emitted by the process."""
        return None


__all__ = ['BaseAddon', 'BasePlugin', 'DisManagerClient', 'ManagedProcess']
