from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import TYPE_CHECKING

import discord

from ...core.bootstrap.i18n import _
from ...core.format import format_bytes
from ...core.managed_process import ManagedProcess
from ...core.system import SystemMetrics, collect_system_metrics

if TYPE_CHECKING:
    from ..client import DisManagerClient

_FOOTER_ICON_URL = (
    'https://raw.githubusercontent.com/mjpr-3435/DisManager/master/assets/branding/dismanager-icon-512.png'
)


async def update_panel(
    client: DisManagerClient,
    *,
    view: discord.ui.View | None,
) -> discord.Message:
    """Collect host metrics and publish or update the DisManager panel embed."""
    channel = client._panel_manager.channel
    error_thread = client._panel_manager.error_thread
    assert channel is not None and client.user is not None and error_thread is not None

    metrics, snapshots = await asyncio.to_thread(_collect_panel_data, client.processes)
    embed = _build_panel_embed(
        metrics,
        client._config.bot_prefix,
        error_thread=error_thread,
        process_snapshots=snapshots,
        footer_icon_url=_FOOTER_ICON_URL,
    )
    return await _publish_or_update_panel(channel, client.user.id, embed, view=view)


# =========================================
#            Internal Helpers
# =========================================


@dataclass(frozen=True, slots=True)
class _ProcessSnapshot:
    name: str
    running: bool
    ram_text: str
    console_thread: discord.Thread | None


def _collect_panel_data(processes: Sequence[ManagedProcess]) -> tuple[SystemMetrics, list[_ProcessSnapshot]]:
    metrics = collect_system_metrics()
    snapshots = [
        _ProcessSnapshot(
            name=proc.name,
            running=(running := proc.is_running()),
            ram_text=format_bytes(proc.ram_usage_bytes()) if running else '0.0 B',
            console_thread=proc.console_thread,
        )
        for proc in processes
    ]
    return metrics, snapshots


def _build_panel_embed(
    metrics: SystemMetrics,
    bot_prefix: str,
    *,
    error_thread: discord.Thread,
    process_snapshots: Sequence[_ProcessSnapshot],
    footer_icon_url: str | None = None,
) -> discord.Embed:
    panel_colour = 0x2F3136
    console_commands = ('start', 'stop', 'kill', 'restart', 'logs', 'plreload')
    panel_commands = ('start', 'stop', 'kill', 'restart', 'plreload', 'adreload')

    console_cmds = ' '.join(f'`{cmd}`' for cmd in console_commands)
    panel_cmds = ' '.join(f'`{bot_prefix}{cmd}`' for cmd in panel_commands)
    description = (
        _(
            'Here you will find an overview of the server resource usage. '
            'Additionally, DisManager recognizes the following commands in the following instances:\n'
        )
        + f'- {_("Console")} : {console_cmds}\n'
        + f'- {_("Panel")} : {panel_cmds}\n'
        + f'- {_("Error Reports")} : {error_thread.mention}'
    )

    embed = discord.Embed(
        title=_('DisManager Panel'),
        description=description,
        colour=panel_colour,
    )
    embed.add_field(
        inline=True,
        name=_('System Resources'),
        value=_ansi_block(
            [
                ('Freq', metrics.cpu_freq),
                ('Load', metrics.cpu_load),
                ('Temp', metrics.cpu_temp),
            ],
            header='CPU',
        ),
    )
    embed.add_field(
        inline=True,
        name='\u200b',
        value=_ansi_block(
            [
                ('Total', metrics.ram_total),
                ('Used', metrics.ram_used),
                ('Load', metrics.ram_load),
            ],
            header='RAM',
        ),
    )
    embed.add_field(
        inline=True,
        name='\u200b',
        value=_ansi_block(
            [
                ('Total', metrics.disk_total),
                ('Used', metrics.disk_used),
                ('Load', metrics.disk_load),
            ],
            header='Storage',
        ),
    )
    visible = process_snapshots[:15]
    for idx, snap in enumerate(visible):
        field_name = (
            f'> {snap.console_thread.mention}'
            if snap.console_thread is not None
            else f'> {snap.name} ({_("creating thread...")})'
        )
        embed.add_field(
            inline=True,
            name=field_name,
            value=_ansi_block(
                [
                    ('State', 'Running' if snap.running else 'Closed'),
                    ('RAM Usage', snap.ram_text),
                ],
                width=26,
            ),
        )
        if (idx + 1) % 2 == 0 and idx + 1 < len(visible):
            embed.add_field(inline=False, name='', value='')

    if len(visible) % 2 == 1 and len(embed.fields) < 25:
        embed.add_field(inline=True, name='', value='')

    warnings: list[str] = []
    if metrics.disk_percent > 90:
        warnings.append(_format_warning(_('[Disk Usage]: Disk usage is over 90%.')))
    if warnings and len(embed.fields) < 25:
        embed.add_field(
            inline=False,
            name=f'> {_("Warnings")}',
            value='\n'.join(f'`{w}`' for w in warnings),
        )

    embed.set_footer(
        text=f"🟢 DisManager v{version('dismanager')}  •  RAM: {metrics.app_ram}",
        icon_url=footer_icon_url,
    )
    return embed


async def _publish_or_update_panel(
    channel: discord.TextChannel,
    bot_user_id: int,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None,
) -> discord.Message:
    messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]

    if not messages:
        return await channel.send(embed=embed, view=view) if view is not None else await channel.send(embed=embed)

    if messages[0].author.id != bot_user_id or not messages[0].embeds:
        while messages:
            await channel.purge()
            messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
        return await channel.send(embed=embed, view=view) if view is not None else await channel.send(embed=embed)

    if view is not None:
        return await messages[0].edit(embed=embed, view=view)
    return await messages[0].edit(embed=embed)


_BLANK_SPACE = '\u200e '


def _format_warning(message: str) -> str:
    warning = f'📌 {message}'
    warning += max(0, 66 - len(warning)) * _BLANK_SPACE
    return warning


def _ansi_block(rows: list[tuple[str, str]], *, header: str | None = None, width: int = 16) -> str:
    gray = '\x1b[0;37m'
    white = '\x1b[1;37m'
    reset = '\x1b[0m'

    label_width = max(7, *(len(label) + 2 for label, _ in rows))
    value_width = max(width - label_width, *(len(value) for _, value in rows))

    lines: list[str] = []
    if header is not None:
        lines.append(f'{white}{header}{reset}')
    lines.extend(
        f'{gray}{f"{label}:":<{label_width}}{reset}{white}{value:>{value_width}}{reset}'
        for label, value in rows
    )
    return '```ansi\n' + '\n'.join(lines) + '\n```'
