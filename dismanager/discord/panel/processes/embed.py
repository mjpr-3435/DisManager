from __future__ import annotations

from collections.abc import Sequence

import discord

from ....core.bootstrap.i18n import _
from ....core.process_store import MAX_PROCESSES, ProcessConfig


def build_processes_embed(processes: Sequence[ProcessConfig]) -> discord.Embed:
    """Build the Processes configuration embed."""
    embed = discord.Embed(
        title=f"> **{_('Processes Configuration')}**",
        description=_(
            'Configure the processes managed by DisManager. '
            'Each process automatically uses a folder matching its name inside `DisManager/`.\n\n'
            '• Select a process from the menu to inspect or edit its settings.\n'
            '• Use **New** to register a process (up to 15) or **Delete** to remove one.'
        ),
        colour=0x2F3136,
    )
    embed.set_footer(text=f"{_('Processes')}: {len(processes)}/{MAX_PROCESSES}")
    return embed
