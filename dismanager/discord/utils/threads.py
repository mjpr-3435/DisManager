from __future__ import annotations

import discord


async def get_or_create_thread(
    channel: discord.TextChannel,
    name: str,
) -> discord.Thread:
    """Return an existing thread by name (unarchiving if needed) or create a new one."""
    target_name = name.strip()

    for active in channel.threads:
        if active.name == target_name:
            return active

    async for archived in channel.archived_threads(limit=None):
        if archived.name == target_name:
            await archived.edit(archived=False)
            return archived

    return await channel.create_thread(name=target_name, type=discord.ChannelType.public_thread)
