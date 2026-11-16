from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import discord
import psutil

from ...core.i18n import Translator
from ...core.processes import ManagedProcess
from ..files.embed import format_bytes

if TYPE_CHECKING:
    from ..client import DisManagerClient


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
        client._,
        error_thread=error_thread,
        process_snapshots=snapshots,
        threads=channel.threads,
    )
    return await _publish_or_update_panel(channel, client.user.id, embed, view=view)


# =========================================
#            Internal Helpers
# =========================================


@dataclass(frozen=True, slots=True)
class _SystemMetrics:
    """Host CPU, RAM, disk, and DisManager process metrics."""

    cpu_freq: str
    cpu_load: str
    cpu_temp: str
    ram_total: str
    ram_used: str
    ram_load: str
    disk_total: str
    disk_used: str
    disk_load: str
    app_ram: str


@dataclass(frozen=True, slots=True)
class _ProcessSnapshot:
    name: str
    running: bool
    ram_text: str


class _TemperatureSensor(Protocol):
    label: str
    current: float


def _collect_panel_data(processes: Sequence[ManagedProcess]) -> tuple[_SystemMetrics, list[_ProcessSnapshot]]:
    metrics = _collect_system_metrics()
    snapshots = [
        _ProcessSnapshot(
            name=proc.name,
            running=(running := proc.is_running()),
            ram_text=format_bytes(proc.ram_usage_bytes()) if running else '0.0 B',
        )
        for proc in processes
    ]
    return metrics, snapshots


def _collect_system_metrics() -> _SystemMetrics:
    """Collect host CPU, RAM, and disk metrics via psutil."""
    freq = psutil.cpu_freq()
    cpu_freq = f'{int(freq.current)} MHz' if freq is not None else '—— MHz'
    cpu_load = f'{psutil.cpu_percent(interval=0.5):.1f} %'
    cpu_temp = _get_cpu_temp()

    ram = psutil.virtual_memory()
    disk_root = str(Path.cwd().anchor or '/')
    disk = psutil.disk_usage(disk_root)

    gb = 1024**3
    return _SystemMetrics(
        cpu_freq=cpu_freq,
        cpu_load=cpu_load,
        cpu_temp=cpu_temp,
        ram_total=f'{ram.total / gb:.1f} GB',
        ram_used=f'{ram.used / gb:.1f} GB',
        ram_load=f'{ram.percent:.1f} %',
        disk_total=f'{disk.total / gb:.1f} GB',
        disk_used=f'{disk.used / gb:.1f} GB',
        disk_load=f'{disk.percent:.1f} %',
        app_ram=_get_process_ram(),
    )


def _build_panel_embed(
    metrics: _SystemMetrics,
    bot_prefix: str,
    translator: Translator,
    *,
    error_thread: discord.Thread,
    process_snapshots: Sequence[_ProcessSnapshot],
    threads: Sequence[discord.Thread],
) -> discord.Embed:
    """Build the Discord embed displaying host system metrics."""
    panel_colour = 0x2F3136
    console_commands = ('start', 'stop', 'kill', 'restart', 'logs', 'plreload')
    panel_commands = ('start', 'stop', 'kill', 'restart', 'plreload', 'adreload')

    console_cmds = ' '.join(f'`{cmd}`' for cmd in console_commands)
    panel_cmds = ' '.join(f'`{bot_prefix}{cmd}`' for cmd in panel_commands)
    description = (
        translator(
            'Here you will find an overview of the server resource usage. '
            'Additionally, DisManager recognizes the following commands in the following instances:\n'
        )
        + f'- {translator("Console")} : {console_cmds}\n'
        + f'- {translator("Panel")} : {panel_cmds}\n'
        + f'- {translator("Error Reports")} : {error_thread.mention}'
    )

    embed = discord.Embed(
        title=translator('DisManager Panel'),
        description=description,
        colour=panel_colour,
    )
    embed.add_field(
        inline=True,
        name=translator('System Resources'),
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
    thread_by_name = {thread.name: thread for thread in threads}
    visible = process_snapshots[:15]
    for idx, snap in enumerate(visible):
        console_thread = thread_by_name.get(f'Console {snap.name}')
        field_name = f'> {console_thread.mention}' if console_thread is not None else f'> {snap.name}'
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

    embed.set_footer(text=f"🟢 DisManager v{version('dismanager')}  •  RAM: {metrics.app_ram}")
    return embed


async def _publish_or_update_panel(
    channel: discord.TextChannel,
    bot_user_id: int,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None,
) -> discord.Message:
    """Publish the panel embed or update the existing bot message in the channel."""
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


def _get_cpu_temp() -> str:
    sensors_fn = getattr(psutil, 'sensors_temperatures', None)
    if sensors_fn is None:
        return '—— °C'

    try:
        temps = cast(Mapping[str, Sequence[_TemperatureSensor]], sensors_fn())
        for sensor in ('coretemp', 'k10temp'):
            if sensor not in temps:
                continue
            for temp in temps[sensor]:
                label = temp.label.lower()
                if 'package id' in label or 'tdie' in label or 'tctl' in label:
                    return f'{int(temp.current)} °C'
    except Exception:
        pass

    return '—— °C'


def _get_process_ram() -> str:
    try:
        rss: float = float(psutil.Process().memory_info().rss)
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if rss < 1024 or unit == 'TB':
                return f'{rss:.1f} {unit}'
            rss /= 1024
    except Exception:
        pass
    return '———'
