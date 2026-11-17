from __future__ import annotations

from typing import TYPE_CHECKING

from .commands import setup as setup_commands
from .events import setup as setup_events

if TYPE_CHECKING:
    from ..client import DisManagerClient


async def setup(bot: DisManagerClient) -> None:
    """Register all DisManager cogs on the bot."""
    await setup_commands(bot)
    await setup_events(bot)


__all__ = ['setup']
