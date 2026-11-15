from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Literal

from .i18n import Translator

_CommandHandler = Callable[[str], Awaitable[bool]]
ProcessAction = Literal['start', 'stop', 'restart', 'kill']


def build_console_handler(
    translator: Translator,
    on_exit: Callable[[], Coroutine[Any, Any, None]],
    on_adreload: Callable[[], Coroutine[Any, Any, int]],
    on_plreload: Callable[[str | None], Coroutine[Any, Any, int]],
    on_process_action: Callable[[ProcessAction, str], Coroutine[Any, Any, str]],
    on_status: Callable[[], str],
) -> _CommandHandler:
    """Create the interactive console command dispatcher."""

    async def handle(raw_command: str) -> bool:
        parts = raw_command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ''

        if cmd == 'exit':
            await on_exit()
            return False

        if cmd == 'adreload':
            count = await on_adreload()
            print(translator('Reloaded {} addon(s).').format(count))
            return True

        if cmd == 'plreload':
            count = await on_plreload(arg or None)
            print(translator('Reloaded {} plugin(s).').format(count))
            return True

        if cmd in ('start', 'stop', 'restart', 'kill'):
            action: ProcessAction = (
                'start'
                if cmd == 'start'
                else 'stop'
                if cmd == 'stop'
                else 'restart'
                if cmd == 'restart'
                else 'kill'
            )
            print(await on_process_action(action, arg))
            return True

        if cmd == 'status':
            print(on_status())
            return True

        print(translator("Unknown command: '{}'.").format(cmd))
        return True

    return handle


async def console_loop(
    handler: _CommandHandler,
    *,
    header: str,
) -> None:
    """Read console commands asynchronously without blocking the event loop."""
    loop = asyncio.get_running_loop()
    lines: asyncio.Queue[str | None] = asyncio.Queue()
    stop_event = threading.Event()

    def _reader() -> None:
        try:
            while not stop_event.is_set():
                if not _wait_for_stdin(stop_event):
                    break
                line = sys.stdin.readline()
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(lines.put_nowait, line or None)
                if not line:
                    break
        except (OSError, ValueError):
            pass

    threading.Thread(target=_reader, daemon=True, name='console-stdin').start()

    try:
        while True:
            print(f'\n{header}')
            sys.stdout.write('>> ')
            sys.stdout.flush()

            line = await lines.get()
            if line is None:
                break

            command = line.strip()
            if not command:
                continue

            should_continue = await handler(command)
            if not should_continue:
                break
    finally:
        stop_event.set()


def _wait_for_stdin(stop_event: threading.Event) -> bool:
    if os.name == 'nt' and sys.stdin.isatty():
        import msvcrt

        while not stop_event.is_set():
            if msvcrt.kbhit():
                return True
            time.sleep(0.05)
        return False
    return True
