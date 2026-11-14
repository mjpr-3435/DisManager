from __future__ import annotations

from importlib.metadata import version

import discord

GUIDE_COLOUR = 0x2F3136


def build_guide_embed() -> discord.Embed:
    """Build the DisManager guide embed."""
    embed = discord.Embed(
        title=f"> DisManager v{version('dismanager')}",
        colour=GUIDE_COLOUR,
        url='https://github.com/mjpr-3435/DisManager',
        description=(
            'The guide will be implemented soon, but in the meantime, you can find it on GitHub.'
            '\n\nPorted by Gemini 4 Hydrogen based on McDis RCON.'
        ),
    )
    embed.set_image(url='https://i.imgur.com/phe4JAf.png')
    return embed
