from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, cast

import discord
from discord.ext import commands

from ....core.commands import ProcessAction, run_process_action

if TYPE_CHECKING:
    from ..client import DisManagerClient

_logger = logging.getLogger(__name__)


class _BotEvents(commands.Cog):
    """Discord event listeners for panel threads and per-process console threads."""

    def __init__(self, bot: DisManagerClient) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_update(self, _before: discord.Thread, after: discord.Thread) -> None:
        if not after.archived:
            return
        error_thread = self.bot._panel_manager.error_thread
        is_error_thread = error_thread is not None and after.id == error_thread.id
        is_console_thread = any(
            proc.console_thread is not None and proc.console_thread.id == after.id
            for proc in self.bot.processes
        )
        if is_error_thread or is_console_thread:
            with contextlib.suppress(discord.HTTPException):
                await after.edit(archived=False)
            self.bot._panel_manager.refresh()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        process = next(
            (
                proc
                for proc in self.bot.processes
                if proc.console_thread is not None and proc.console_thread.id == message.channel.id
            ),
            None,
        )
        if process is None:
            return

        cmd = message.content.strip().lower()
        if cmd in ('start', 'stop', 'kill', 'restart', 'plreload'):
            action = cast(ProcessAction, cmd)
            source = f'Console thread ({message.author} id={message.author.id})'
            ok, feedback = await run_process_action(self.bot, action, process.name, markdown=True, source=source)
            if not ok:
                await message.channel.send(feedback, delete_after=5)
        elif cmd == 'logs':
            _logger.info(
                "Console thread command 'logs' on '%s' by %s (id=%s)",
                process.name,
                message.author,
                message.author.id,
            )
            await process._send_logs()
        else:
            process.execute(message.content)


async def setup(bot: DisManagerClient) -> None:
    """Register the Discord event-listener cog on ``bot``."""
    await bot.add_cog(_BotEvents(bot))
