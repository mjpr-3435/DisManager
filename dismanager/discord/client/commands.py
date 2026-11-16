from __future__ import annotations

import asyncio
import contextlib
import io
from typing import TYPE_CHECKING, Literal

import discord
from discord.ext import commands

from ...core.processes import ProcessConfigError

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

        data = self.bot.log_session.recent_bytes()
        if not data:
            await ctx.send(self.bot._('The log file is currently empty.'))
            return

        file = discord.File(io.BytesIO(data), filename=self.bot.log_session.filename)
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
        if self.bot.panel is None or ctx.channel.id != self.bot.panel.id:
            return
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()
        target = name.strip() or None
        if target is not None and self.bot.find_process(target) is None:
            await ctx.send(self.bot._('✖ Process `{}` not found.').format(target), delete_after=3)
            return
        count = await self.bot.reload_plugins(target)
        await ctx.send(self.bot._('✔ Reloaded {} plugin(s).').format(count), delete_after=2)

    @commands.command(name='adreload')
    async def adreload_command(self, ctx: commands.Context[DisManagerClient]) -> None:
        if self.bot.panel is None or ctx.channel.id != self.bot.panel.id:
            return
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()
        count = await self.bot.reload_addons()
        await ctx.send(f'✔ Reloaded {count} addon(s).', delete_after=2)

    async def _run_process_command(
        self,
        ctx: commands.Context[DisManagerClient],
        action: Literal['start', 'stop', 'kill', 'restart'],
        name: str,
    ) -> None:
        if self.bot.panel is None or ctx.channel.id != self.bot.panel.id:
            return

        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()

        target = name.strip()
        if not target:
            await ctx.send(
                f'✖ Specify the process. E.g.: `{ctx.prefix}{action} <name>`',
                delete_after=5,
            )
            return

        process = self.bot.find_process(target)
        if process is None:
            await ctx.send(f'✖ Process `{target}` not found.', delete_after=5)
            return

        if action == 'start':
            if process.is_running():
                await ctx.send(f'✖ `[{process.name}]`: The process was already open.', delete_after=2)
                return
            try:
                process.start()
            except ProcessConfigError as exc:
                await ctx.send(f'✖ `[{process.name}]`: {exc}', delete_after=5)
                return
            await ctx.send(f'✔ `[{process.name}]`: Initializing process.', delete_after=2)
            return

        if not process.is_running():
            await ctx.send(f'✖ `[{process.name}]`: The process was not open.', delete_after=2)
            return

        if action == 'stop':
            process.stop()
            await ctx.send(f'✔ `[{process.name}]`: Stopping process.', delete_after=2)
        elif action == 'kill':
            process.kill()
            await ctx.send(f'✔ `[{process.name}]`: Killing process.', delete_after=2)
        else:
            asyncio.create_task(process.restart())
            await ctx.send(f'✔ `[{process.name}]`: Restarting process.', delete_after=2)


async def setup(bot: DisManagerClient) -> None:
    """Register DisManager Discord commands on the bot."""
    await bot.add_cog(_BotCommands(bot))
