from __future__ import annotations

import contextlib
import io
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ....core.bootstrap.i18n import _
from ....core.commands import (
    ProcessAction,
    reload_addons_command,
    run_all_processes_action,
    run_process_action,
)

if TYPE_CHECKING:
    from ..client import DisManagerClient


class _BotCommands(commands.Cog):
    """Discord text commands for DisManager."""

    def __init__(self, bot: DisManagerClient) -> None:
        self.bot = bot

    @commands.command(name='log')
    async def log_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        error_thread = self.bot._panel_manager.error_thread
        if error_thread is None or ctx.channel.id != error_thread.id:
            return

        data = self.bot._log_session.recent_bytes()
        if not data:
            await ctx.send(_('The log file is currently empty.'))
            return

        file = discord.File(io.BytesIO(data), filename=self.bot._log_session.filename)
        await ctx.send(file=file)

    @commands.command(name='start')
    async def start_command(self, ctx: commands.Context[DisManagerClient], *, name: str = '') -> None:
        await self._run_process_command(ctx, 'start', name)

    @commands.command(name='stop')
    async def stop_command(self, ctx: commands.Context[DisManagerClient], *, name: str = '') -> None:
        await self._run_process_command(ctx, 'stop', name)

    @commands.command(name='kill')
    async def kill_command(self, ctx: commands.Context[DisManagerClient], *, name: str = '') -> None:
        await self._run_process_command(ctx, 'kill', name)

    @commands.command(name='restart')
    async def restart_command(self, ctx: commands.Context[DisManagerClient], *, name: str = '') -> None:
        await self._run_process_command(ctx, 'restart', name)

    @commands.command(name='plreload')
    async def plreload_command(self, ctx: commands.Context[DisManagerClient], *, name: str = '') -> None:
        await self._run_process_command(ctx, 'plreload', name)

    @commands.command(name='start-all')
    async def start_all_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        await self._run_all_processes_command(ctx, 'start')

    @commands.command(name='stop-all')
    async def stop_all_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        await self._run_all_processes_command(ctx, 'stop')

    @commands.command(name='kill-all')
    async def kill_all_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        await self._run_all_processes_command(ctx, 'kill')

    @commands.command(name='restart-all')
    async def restart_all_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        await self._run_all_processes_command(ctx, 'restart')

    @commands.command(name='plreload-all')
    async def plreload_all_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        await self._run_all_processes_command(ctx, 'plreload')

    @commands.command(name='adreload')
    async def adreload_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        if self.bot._panel_manager.channel is None or ctx.channel.id != self.bot._panel_manager.channel.id:
            return
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()
        _ok, message = await reload_addons_command(self.bot)
        await ctx.send(f'✔ {message}', delete_after=2)

    async def _run_process_command(
        self,
        ctx: commands.Context[DisManagerClient],
        action: ProcessAction,
        name: str,
    ) -> None:
        if self.bot._panel_manager.channel is None or ctx.channel.id != self.bot._panel_manager.channel.id:
            return

        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()

        ok, message = await run_process_action(self.bot, action, name, markdown=True)
        prefix = '✔' if ok else '✖'
        await ctx.send(f'{prefix} {message}', delete_after=2 if ok else 5)

    async def _run_all_processes_command(
        self,
        ctx: commands.Context[DisManagerClient],
        action: ProcessAction,
    ) -> None:
        if self.bot._panel_manager.channel is None or ctx.channel.id != self.bot._panel_manager.channel.id:
            return

        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()

        ok, message = await run_all_processes_action(self.bot, action, markdown=True)
        if not ok and '\n' not in message:
            message = f'✖ {message}'
        await ctx.send(message, delete_after=3 if ok else 5)


async def setup(bot: DisManagerClient) -> None:
    """Register DisManager Discord commands on the bot."""
    await bot.add_cog(_BotCommands(bot))
