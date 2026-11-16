from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import psutil

from ..format import format_bytes


@dataclass(frozen=True, slots=True)
class SystemMetrics:
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


def collect_system_metrics() -> SystemMetrics:
    """Collect host CPU, RAM, disk, and DisManager process metrics via ``psutil``."""
    freq = psutil.cpu_freq()
    cpu_freq = f'{int(freq.current)} MHz' if freq is not None else '—— MHz'
    cpu_load = f'{psutil.cpu_percent(interval=0.5):.1f} %'
    cpu_temp = _get_cpu_temp()

    ram = psutil.virtual_memory()
    disk_root = str(Path.cwd().anchor or '/')
    disk = psutil.disk_usage(disk_root)

    gb = 1024**3
    return SystemMetrics(
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


# =========================================
#            Internal Helpers
# =========================================


class _TemperatureSensor(Protocol):
    label: str
    current: float


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
        rss = psutil.Process().memory_info().rss
        return format_bytes(int(rss))
    except Exception:
        return '—— MB'
