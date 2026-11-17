from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Literal

from ..bootstrap.i18n import _
from ..process_store import ProcessConfigError

if TYPE_CHECKING:
    from ...discord.client import DisManagerClient
    from ..managed_process import ManagedProcess

ProcessAction = Literal['start', 'stop', 'kill', 'restart', 'plreload']

_logger = logging.getLogger(__name__)


async def run_process_action(
    client: DisManagerClient,
    action: ProcessAction,
    name: str,
    *,
    markdown: bool = False,
    source: str = 'unknown',
) -> tuple[bool, str]:
    """Resolve a process by name, run ``action``, and return ``(ok, message)``."""
    tick = '`' if markdown else ''
    prefix = client.config.bot_prefix if markdown else ''
    target = name.strip()
    if not target:
        return _format_result(
            False,
            _('Specify the process. E.g.: {0}{1}{2} <name>{0} or {0}{1}{2}-all{0}').format(
                tick, prefix, action
            ),
            markdown=markdown,
        )

    process = client.find_process(target)
    if process is None:
        _logger.info("Control action '%s' on '%s' requested by %s -> not found", action, target, source)
        ref = f'`{target}`' if markdown else f"'{target}'"
        return _format_result(False, _('Process {} not found.').format(ref), markdown=markdown)

    ok, detail = await _execute_process_action(process, action)
    _logger.info(
        "Control action '%s' on '%s' requested by %s -> %s",
        action,
        process.name,
        source,
        'ok' if ok else 'failed',
    )
    return _format_result(ok, f'{tick}[{process.name}]{tick}: {detail}', markdown=markdown)


async def run_all_processes_action(
    client: DisManagerClient,
    action: ProcessAction,
    *,
    markdown: bool = False,
    source: str = 'unknown',
) -> tuple[bool, str]:
    """Run ``action`` across all configured processes and return ``(ok, summary)``."""
    processes = client.processes
    if not processes:
        _logger.info("Control action '%s-all' requested by %s -> no processes", action, source)
        return _format_result(False, _('No processes configured.'), markdown=markdown)

    tick = '`' if markdown else ''
    lines: list[str] = []
    any_ok = False
    for process in processes:
        ok, detail = await _execute_process_action(process, action)
        if ok:
            any_ok = True
        if ok or action == 'start':
            _ok, line = _format_result(ok, f'{tick}[{process.name}]{tick}: {detail}', markdown=markdown)
            lines.append(line if markdown else f'  {line}')

    _logger.info("Control action '%s-all' requested by %s -> %s", action, source, 'ok' if any_ok else 'failed')
    if not lines:
        return _format_result(False, _('No eligible processes for {}.').format(action), markdown=markdown)
    return any_ok, '\n'.join(lines)


async def reload_addons_command(
    client: DisManagerClient,
    *,
    markdown: bool = False,
    source: str = 'unknown',
) -> str:
    """Reload all DisManager addons and return the formatted status message."""
    count = await client.reload_addons()
    _logger.info("Control action 'adreload' requested by %s -> reloaded %d addon(s)", source, count)
    _ok, message = _format_result(True, _('Reloaded {} addon(s).').format(count), markdown=markdown)
    return message


# =========================================
#            Internal Helpers
# =========================================


def _format_result(ok: bool, message: str, *, markdown: bool) -> tuple[bool, str]:
    if not markdown:
        return ok, message
    marker = '✔' if ok else '✖'
    return ok, f'{marker} {message}'


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
