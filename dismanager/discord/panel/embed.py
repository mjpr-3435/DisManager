from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Protocol, cast

import discord
import psutil

from ...core.i18n import Translator


async def update_panel(
    channel: discord.TextChannel,
    bot_user_id: int,
    bot_prefix: str,
    translator: Translator,
    *,
    error_thread: discord.Thread | None = None,
    view: discord.ui.View | None = None,
) -> discord.Message:
    """Collect host metrics and publish or update the DisManager panel embed."""
    metrics = await asyncio.to_thread(_collect_system_metrics)
    embed = _build_panel_embed(metrics, bot_prefix, translator, error_thread=error_thread)
    return await _publish_or_update_panel(channel, bot_user_id, embed, view=view)


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


class _TemperatureSensor(Protocol):
    label: str
    current: float


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
    error_thread: discord.Thread | None = None,
) -> discord.Embed:
    """Build the Discord embed displaying host system metrics."""
    panel_colour = 0x2F3136
    console_commands = ('start', 'stop', 'kill', 'restart', 'plreload')
    panel_commands = ('start', 'stop', 'kill', 'restart', 'plreload', 'adreload')

    console_cmds = ' '.join(f'`{cmd}`' for cmd in console_commands)
    panel_cmds = ' '.join(f'`{bot_prefix}{cmd}`' for cmd in panel_commands)
    description = (
        translator(
            'Here you will find an overview of the server resource usage. '
            'Additionally, DisManager recognizes the following commands in the following instances:\n'
        )
        + f'- {translator("Console")} : {console_cmds}\n'
        + f'- {translator("Panel")} : {panel_cmds}'
    )
    if error_thread is not None:
        description += f'\n- {translator("Error Reports")} : {error_thread.mention}'

    embed = discord.Embed(
        title=translator('DisManager Panel'),
        description=description,
        colour=panel_colour,
    )
    embed.add_field(
        inline=True,
        name='> CPU',
        value=_ansi_block([
            ('Freq', metrics.cpu_freq),
            ('Load', metrics.cpu_load),
            ('Temp', metrics.cpu_temp),
        ]),
    )
    embed.add_field(
        inline=True,
        name='> RAM',
        value=_ansi_block([
            ('Total', metrics.ram_total),
            ('Used', metrics.ram_used),
            ('Load', metrics.ram_load),
        ]),
    )
    embed.add_field(
        inline=True,
        name='> Storage',
        value=_ansi_block([
            ('Total', metrics.disk_total),
            ('Used', metrics.disk_used),
            ('Load', metrics.disk_load),
        ]),
    )
    embed.set_footer(text=f"🟢 DisManager v{version('dismanager')}  •  RAM: {metrics.app_ram}")
    return embed


async def _publish_or_update_panel(
    channel: discord.TextChannel,
    bot_user_id: int,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None = None,
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


def _ansi_block(rows: list[tuple[str, str]]) -> str:
    gray = '\x1b[0;37m'
    white = '\x1b[1;37m'
    reset = '\x1b[0m'

    lines = [f'{gray}{f"{label}:":<7}{reset}{white}{value:>9}{reset}' for label, value in rows]
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
