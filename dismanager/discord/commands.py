from __future__ import annotations

import io
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ..core.logs import get_recent_log_bytes, get_session_log_filename

if TYPE_CHECKING:
    from .client import DisManagerClient


class _BotCommands(commands.Cog):
    """Discord text commands for DisManager."""

    def __init__(self, bot: DisManagerClient) -> None:
        self.bot = bot

    @commands.command(name='log')
    async def log_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        if self.bot.error_thread is None or ctx.channel.id != self.bot.error_thread.id:
            return

        data = get_recent_log_bytes()
        if not data:
            await ctx.send(self.bot._('The log file is currently empty.'))
            return

        file = discord.File(io.BytesIO(data), filename=get_session_log_filename())
        await ctx.send(file=file)


async def setup(bot: DisManagerClient) -> None:
    """Register DisManager Discord commands on the bot."""
    await bot.add_cog(_BotCommands(bot))
