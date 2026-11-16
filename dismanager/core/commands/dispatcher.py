from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from ..bootstrap.i18n import _
from ..process_store import ProcessConfigError

if TYPE_CHECKING:
    from ...discord.client import DisManagerClient
    from ..managed_process import ManagedProcess

ProcessAction = Literal['start', 'stop', 'kill', 'restart', 'plreload']


async def run_process_action(
    client: DisManagerClient,
    action: ProcessAction,
    name: str,
    *,
    markdown: bool = False,
) -> tuple[bool, str]:
    """Resolve a process by name, run ``action``, and return ``(ok, message)``."""
    tick = '`' if markdown else ''
    prefix = client.config.bot_prefix if markdown else ''
    target = name.strip()
    if not target:
        return False, _('Specify the process. E.g.: {0}{1}{2} <name>{0} or {0}{1}{2}-all{0}').format(
            tick, prefix, action
        )

    process = client.find_process(target)
    if process is None:
        ref = f'`{target}`' if markdown else f"'{target}'"
        return False, _('Process {} not found.').format(ref)

    ok, detail = await _execute_process_action(process, action)
    return ok, f'{tick}[{process.name}]{tick}: {detail}'


async def run_all_processes_action(
    client: DisManagerClient,
    action: ProcessAction,
    *,
    markdown: bool = False,
) -> tuple[bool, str]:
    """Run ``action`` across all configured processes and return ``(ok, summary)``."""
    processes = client.processes
    if not processes:
        return False, _('No processes configured.')

    tick = '`' if markdown else ''
    lines: list[str] = []
    any_ok = False
    for process in processes:
        ok, detail = await _execute_process_action(process, action)
        if ok:
            any_ok = True
        if ok or action == 'start':
            if markdown:
                marker = '✔' if ok else '✖'
                lines.append(f'{marker} {tick}[{process.name}]{tick}: {detail}')
            else:
                lines.append(f'  [{process.name}]: {detail}')

    if not lines:
        return False, _('No eligible processes for {}.').format(action)
    return any_ok, '\n'.join(lines)


async def reload_addons_command(client: DisManagerClient) -> tuple[bool, str]:
    """Reload all DisManager addons and return ``(ok, message)``."""
    count = await client.reload_addons()
    return True, _('Reloaded {} addon(s).').format(count)


# =========================================
#            Internal Helpers
# =========================================


async def _execute_process_action(process: ManagedProcess, action: ProcessAction) -> tuple[bool, str]:
    if action == 'start':
        if process.is_running():
            return False, _('The process is already running.')
        try:
            process.start()
        except ProcessConfigError as exc:
            return False, str(exc)
        return True, _('Initializing process.')

    if not process.is_running():
        return False, _('The process is not running.')

    if action == 'stop':
        process.stop()
        return True, _('Stopping process.')
    if action == 'kill':
        process.kill()
        return True, _('Killing process.')
    if action == 'restart':
        asyncio.create_task(process.restart())
        return True, _('Restarting process.')
    if action == 'plreload':
        count = await process.reload_plugins()
        return True, _('Reloaded {} plugin(s).').format(count)
    raise ValueError(f'Unsupported process action: {action}')
