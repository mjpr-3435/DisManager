from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time
from typing import TYPE_CHECKING, Literal, cast

from ....core.bootstrap.i18n import _
from ....core.process_store import ProcessConfigError

if TYPE_CHECKING:
    from ....core.managed_process import ManagedProcess
    from ..client import DisManagerClient


class ConsoleManager:
    """Manages the local interactive terminal loop and its DisManager commands."""

    _task: asyncio.Task[None] | None

    def __init__(self, client: DisManagerClient) -> None:
        self._client = client
        self._task = None


    # --- Internal Behaviour ---

    async def _loop(self) -> None:
        """Read console commands asynchronously without blocking the event loop."""
        header = (
            f"{_('Commands')}: "
            'start[-all], stop[-all], restart[-all], kill[-all], plreload[-all], adreload, status, exit'
        )
        loop = asyncio.get_running_loop()
        # Bridge queue between the blocking stdin thread and the asyncio event loop (None signals EOF).
        lines: asyncio.Queue[str | None] = asyncio.Queue()
        stop_event = threading.Event()

        def _reader() -> None:
            try:
                while not stop_event.is_set():
                    # Poll stdin with a short timeout so stop_event can interrupt waiting on shutdown.
                    if not _wait_for_stdin(stop_event):
                        break
                    line = sys.stdin.readline()
                    # asyncio.Queue is not thread-safe; schedule put_nowait onto the event loop thread.
                    # Empty string '' means EOF (stdin closed), converted to None to stop the consumer.
                    with contextlib.suppress(RuntimeError):
                        loop.call_soon_threadsafe(lines.put_nowait, line or None)
                    if not line:
                        break
            except (OSError, ValueError):
                pass

        # Daemon thread ensures stdin reading never blocks process exit if cancelled mid-read.
        threading.Thread(target=_reader, daemon=True, name='console-stdin').start()

        try:
            while True:
                print(f'\n{header}')
                sys.stdout.write('>> ')
                sys.stdout.flush()

                # Yield control back to the bot/Discord loop until the reader thread pushes a line.
                line = await lines.get()
                if line is None:
                    break

                command = line.strip()
                if not command:
                    continue

                if not await self._handle(command):
                    break
        finally:
            # Signal the stdin reader thread to stop whether exiting normally or via task cancellation.
            stop_event.set()

    async def _handle(self, raw_command: str) -> bool:
        parts = raw_command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ''

        if cmd == 'exit':
            await self._client.close()
            return False

        if cmd == 'adreload':
            count = await self._client.reload_addons()
            print(_('Reloaded {} addon(s).').format(count))
            return True

        if cmd in ('start', 'stop', 'restart', 'kill', 'plreload'):
            action = cast(Literal['start', 'stop', 'restart', 'kill', 'plreload'], cmd)
            print(await self._process_action(action, arg))
            return True

        if cmd in ('start-all', 'stop-all', 'restart-all', 'kill-all', 'plreload-all'):
            action = cast(Literal['start', 'stop', 'restart', 'kill', 'plreload'], cmd.removesuffix('-all'))
            print(await self._process_action_all(action))
            return True

        if cmd == 'status':
            print(self._status())
            return True

        print(_("Unknown command: '{}'.").format(cmd))
        return True

    async def _process_action(self, action: Literal['start', 'stop', 'restart', 'kill', 'plreload'], name: str) -> str:
        target = name.strip()
        if not target:
            return _('Specify the process. E.g.: {} <name> or {}-all').format(action, action)

        process = self._client.find_process(target)
        if process is None:
            return _("Process '{}' not found.").format(target)

        _ok, message = await self._execute_process_action(process, action)
        return message

    async def _process_action_all(self, action: Literal['start', 'stop', 'restart', 'kill', 'plreload']) -> str:
        processes = self._client.processes
        if not processes:
            return _('No processes configured.')

        lines: list[str] = []
        for process in processes:
            ok, message = await self._execute_process_action(process, action)
            if ok or action == 'start':
                lines.append(f'  {message}')
        return '\n'.join(lines) if lines else _('No eligible processes for {}.').format(action)

    async def _execute_process_action(
        self,
        process: ManagedProcess,
        action: Literal['start', 'stop', 'restart', 'kill', 'plreload'],
    ) -> tuple[bool, str]:
        if action == 'start':
            if process.is_running():
                return False, _('[{}]: The process is already running.').format(process.name)
            try:
                process.start()
            except ProcessConfigError as exc:
                return False, f'[{process.name}]: {exc}'
            return True, _('[{}]: Initializing process.').format(process.name)

        if not process.is_running():
            return False, _('[{}]: The process is not running.').format(process.name)

        if action == 'stop':
            process.stop()
            return True, _('[{}]: Stopping process.').format(process.name)
        if action == 'kill':
            process.kill()
            return True, _('[{}]: Killing process.').format(process.name)
        if action == 'restart':
            asyncio.create_task(process.restart())
            return True, _('[{}]: Restarting process.').format(process.name)
        if action == 'plreload':
            count = await process.reload_plugins()
            return True, _('[{}]: Reloaded {} plugin(s).').format(process.name, count)
        raise ValueError(f'Unsupported process action: {action}')

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
    
    # --- Internal API ---

    def start(self) -> None:
        """Start the interactive console task."""
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        """Cancel the local console task if it is still running."""
        if self._task is not None and self._task is not asyncio.current_task():
            self._task.cancel()

# =========================================
#            Internal Helpers
# =========================================


def _wait_for_stdin(stop_event: threading.Event) -> bool:
    if not sys.stdin.isatty():
        return True

    if os.name == 'nt':
        import msvcrt

        while not stop_event.is_set():
            if msvcrt.kbhit():
                return True
            time.sleep(0.05)
        return False

    if os.name == 'posix':
        import select

        while not stop_event.is_set():
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if ready:
                return True
        return False

    return True
