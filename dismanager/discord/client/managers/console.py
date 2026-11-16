from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time
from typing import TYPE_CHECKING, cast

from ....core.bootstrap.i18n import _
from ....core.commands import (
    ProcessAction,
    reload_addons_command,
    run_all_processes_action,
    run_process_action,
)

if TYPE_CHECKING:
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
            _ok, message = await reload_addons_command(self._client)
            print(message)
            return True

        if cmd in ('start', 'stop', 'restart', 'kill', 'plreload'):
            action = cast(ProcessAction, cmd)
            _ok, message = await run_process_action(self._client, action, arg)
            print(message)
            return True

        if cmd in ('start-all', 'stop-all', 'restart-all', 'kill-all', 'plreload-all'):
            action = cast(ProcessAction, cmd.removesuffix('-all'))
            _ok, message = await run_all_processes_action(self._client, action)
            print(message)
            return True

        if cmd == 'status':
            print(self._status())
            return True

        print(_("Unknown command: '{}'.").format(cmd))
        return True

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
