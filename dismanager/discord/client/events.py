from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from ...core.bootstrap.i18n import _
from ...core.processes import ProcessConfigError

if TYPE_CHECKING:
    from .client import DisManagerClient

_ERROR_THREAD_NAME = 'Error Reports'


class _BotEvents(commands.Cog):
    """Discord event listeners for panel threads and per-process console threads."""

    def __init__(self, bot: DisManagerClient) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_update(self, _before: discord.Thread, after: discord.Thread) -> None:
        panel = self.bot._panel_manager.channel
        if panel is None or after.parent_id != panel.id or not after.archived:
            return
        thread_proc = after.name.removeprefix('Console ')
        if after.name == _ERROR_THREAD_NAME or self.bot._processes_manager.get_config(thread_proc) is not None:
            with contextlib.suppress(discord.HTTPException):
                await after.edit(archived=False)
            self.bot._panel_manager.refresh()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        panel = self.bot._panel_manager.channel
        if message.author.bot or panel is None:
            return

        if (
            not isinstance(message.channel, discord.Thread)
            or message.channel.parent_id != panel.id
            or not message.channel.name.startswith('Console ')
        ):
            return

        target_name = message.channel.name.removeprefix('Console ').strip()
        process = self.bot.find_process(target_name)
        if process is None:
            return

        cmd = message.content.strip().lower()
        if cmd == 'start':
            try:
                process.start()
            except ProcessConfigError as exc:
                await message.channel.send(f'✖ {exc}')
        elif cmd == 'stop':
            process.stop()
        elif cmd == 'kill':
            process.kill()
        elif cmd == 'restart':
            asyncio.create_task(process.restart())
        elif cmd == 'logs':
            await process.send_logs()
        elif cmd == 'plreload':
            count = await process.reload_plugins()
            await message.channel.send(_('✔ Reloaded {} plugin(s).').format(count), delete_after=2)
        else:
            process.execute(message.content)


async def setup(bot: DisManagerClient) -> None:
    """Register the Discord event-listener cog on ``bot``."""
    await bot.add_cog(_BotEvents(bot))
