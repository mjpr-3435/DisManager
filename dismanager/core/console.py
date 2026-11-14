from __future__ import annotations

import asyncio
import sys
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
    while True:
        if header is not None:
            print(f'\n{header}')
        sys.stdout.write(prompt)
        sys.stdout.flush()

        line = await asyncio.to_thread(sys.stdin.readline)
        if line == '':
            break

        command = line.strip()
        if not command:
            continue

        should_continue = await handler(command)
        if not should_continue:
            break
