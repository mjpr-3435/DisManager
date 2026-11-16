from __future__ import annotations

import math


def format_bytes(total: int) -> str:
    """Format a byte count into a human-readable size string."""
    units = ('B', 'KB', 'MB', 'GB', 'TB')
    unit_idx = min(int(math.log(total, 1024)), len(units) - 1) if total > 0 else 0
    return f'{total / (1024**unit_idx):.1f} {units[unit_idx]}'
