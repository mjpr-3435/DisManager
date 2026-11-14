from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from .i18n import Translator

CommandHandler = Callable[[str], Awaitable[bool]]


def build_console_handler(
    translator: Translator,
    on_exit: Callable[[], Coroutine[Any, Any, None]],
) -> CommandHandler:
    """Create the interactive console command dispatcher."""
    pending_commands = {'start', 'stop', 'restart', 'kill', 'plreload', 'adreload', 'status'}

    async def handle(raw_command: str) -> bool:
        cmd = raw_command.split()[0].lower()
        if cmd == 'exit':
            asyncio.create_task(on_exit())
            return False

        if cmd in pending_commands:
            print(translator("Command '{}' is not implemented yet.").format(cmd))
            return True

        print(translator("Unknown command: '{}'.").format(cmd))
        return True

    return handle


async def console_loop(
    handler: CommandHandler,
    *,
    header: str | None = None,
    prompt: str = '>> ',
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
            if header is not None:
                print(f'\n{header}')
            sys.stdout.write(prompt)
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
