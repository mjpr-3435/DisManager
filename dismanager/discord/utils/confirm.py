from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord

_EMBED_COLOUR = 0x2F3136

_InteractionCallback = Callable[[discord.Interaction[Any]], Awaitable[None]]


async def confirmation_request(
    description: str,
    *,
    interaction: discord.Interaction[Any],
    on_confirmation: _InteractionCallback,
) -> None:
    """Send an ephemeral confirmation prompt with ✔ and ✖ buttons."""

    class ConfirmationView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=120)

        @discord.ui.button(label='✔', style=discord.ButtonStyle.gray)
        async def confirm_button(
            self,
            btn_interaction: discord.Interaction[Any],
            _button: discord.ui.Button[Any],
        ) -> None:
            await on_confirmation(btn_interaction)

        @discord.ui.button(label='✖', style=discord.ButtonStyle.red)
        async def cancel_button(
            self,
            btn_interaction: discord.Interaction[Any],
            _button: discord.ui.Button[Any],
        ) -> None:
            await btn_interaction.response.edit_message(delete_after=0)

    await interaction.response.send_message(
        embed=discord.Embed(description=description, colour=_EMBED_COLOUR),
        view=ConfirmationView(),
        ephemeral=True,
    )
