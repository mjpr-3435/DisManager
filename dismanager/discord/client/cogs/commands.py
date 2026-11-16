from __future__ import annotations

import asyncio
import contextlib
import io
from typing import TYPE_CHECKING, Literal

import discord
from discord.ext import commands

from ....core.bootstrap.i18n import _
from ....core.processes import ProcessConfigError

if TYPE_CHECKING:
    from ....core.processes import ManagedProcess
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
        count = await self.bot.reload_addons()
        await ctx.send(f'✔ Reloaded {count} addon(s).', delete_after=2)

    async def _run_process_command(
        self,
        ctx: commands.Context[DisManagerClient],
        action: Literal['start', 'stop', 'kill', 'restart', 'plreload'],
        name: str,
    ) -> None:
        if self.bot._panel_manager.channel is None or ctx.channel.id != self.bot._panel_manager.channel.id:
            return

        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()

        target = name.strip()
        if not target:
            await ctx.send(
                _('✖ Specify the process. E.g.: `{}{} <name>` or `{}{}-all`').format(
                    ctx.prefix, action, ctx.prefix, action
                ),
                delete_after=5,
            )
            return

        process = self.bot.find_process(target)
        if process is None:
            await ctx.send(f'✖ Process `{target}` not found.', delete_after=5)
            return

        ok, feedback = await self._execute_process_action(process, action)
        await ctx.send(feedback, delete_after=2 if ok else 5)

    async def _run_all_processes_command(
        self,
        ctx: commands.Context[DisManagerClient],
        action: Literal['start', 'stop', 'kill', 'restart', 'plreload'],
    ) -> None:
        if self.bot._panel_manager.channel is None or ctx.channel.id != self.bot._panel_manager.channel.id:
            return

        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()

        processes = self.bot.processes
        if not processes:
            await ctx.send(_('✖ No processes configured.'), delete_after=3)
            return

        affected = 0
        for process in processes:
            ok, feedback = await self._execute_process_action(process, action)
            if ok:
                affected += 1
            elif feedback.startswith('✖ `') and 'ProcessConfigError' not in feedback:
                continue

        await ctx.send(
            _('✔ Executed `{}` on {} process(es).').format(action, affected),
            delete_after=3,
        )

    async def _execute_process_action(
        self,
        process: ManagedProcess,
        action: Literal['start', 'stop', 'kill', 'restart', 'plreload'],
    ) -> tuple[bool, str]:
        if action == 'start':
            if process.is_running():
                return False, f'✖ `[{process.name}]`: The process was already open.'
            try:
                process.start()
            except ProcessConfigError as exc:
                return False, f'✖ `[{process.name}]`: {exc}'
            return True, f'✔ `[{process.name}]`: Initializing process.'

        if not process.is_running():
            return False, f'✖ `[{process.name}]`: The process was not open.'

        if action == 'stop':
            process.stop()
            return True, f'✔ `[{process.name}]`: Stopping process.'
        if action == 'kill':
            process.kill()
            return True, f'✔ `[{process.name}]`: Killing process.'
        if action == 'restart':
            asyncio.create_task(process.restart())
            return True, f'✔ `[{process.name}]`: Restarting process.'
        if action == 'plreload':
            count = await process.reload_plugins()
            return True, _('✔ `[{}`]: Reloaded {} plugin(s).').format(process.name, count)
        raise ValueError(f'Unsupported process action: {action}')


async def setup(bot: DisManagerClient) -> None:
    """Register DisManager Discord commands on the bot."""
    await bot.add_cog(_BotCommands(bot))
