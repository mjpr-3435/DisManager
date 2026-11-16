from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ...core.bootstrap.i18n import _
from ...core.console import ProcessAction, build_console_handler, console_loop
from ...core.processes import ProcessConfigError

if TYPE_CHECKING:
    from .client import DisManagerClient


class ConsoleManager:
    """Manages the local interactive terminal loop and its DisManager commands."""

    def __init__(self, client: DisManagerClient) -> None:
        self._client = client
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the interactive console task."""
        header = (
            f"{_('Commands')}: "
            'start, stop, restart, kill, plreload, adreload, status, exit'
        )
        handler = build_console_handler(
            self._client.close,
            self._client.reload_addons,
            self._client._processes_manager.reload_plugins,
            self._process_action,
            self._status,
        )
        self._task = asyncio.create_task(console_loop(handler, header=header))

    def stop(self) -> None:
        """Cancel the local console task if it is still running."""
        current = asyncio.current_task()
        if self._task is not None and self._task is not current and not self._task.done():
            self._task.cancel()

    async def _process_action(self, action: ProcessAction, name: str) -> str:
        target = name.strip()
        if not target:
            return _('Specify the process. E.g.: {} <name>').format(action)

        process = self._client.find_process(target)
        if process is None:
            return _("Process '{}' not found.").format(target)

        if action == 'start':
            if process.is_running():
                return _('[{}]: The process is already running.').format(process.name)
            try:
                process.start()
            except ProcessConfigError as exc:
                return f'[{process.name}]: {exc}'
            return _('[{}]: Initializing process.').format(process.name)

        if not process.is_running():
            return _('[{}]: The process is not running.').format(process.name)

        if action == 'stop':
            process.stop()
            return _('[{}]: Stopping process.').format(process.name)
        if action == 'kill':
            process.kill()
            return _('[{}]: Killing process.').format(process.name)

        asyncio.create_task(process.restart())
        return _('[{}]: Restarting process.').format(process.name)

    def _status(self) -> str:
        processes = self._client.processes
        if not processes:
            return _('No processes configured.')

        lines: list[str] = []
        for proc in processes:
            if proc.is_running():
                ram_mb = proc.ram_usage_bytes() / (1024 * 1024)
                lines.append(f'  • {proc.name}: {_("Online")} ({ram_mb:.1f} MB)')
            else:
                lines.append(f'  • {proc.name}: {_("Offline")}')
        return '\n'.join(lines)
