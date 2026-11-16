from __future__ import annotations

from pathlib import Path

import discord

from ....core.files import build_file_preview_text, is_previewable_image


def build_file_attachment(path: Path) -> discord.File | None:
    """Return a Discord attachment if ``path`` is a previewable image."""
    if not is_previewable_image(path):
        return None
    return discord.File(path, filename=f'preview{path.suffix.lower()}')


def populate_file_preview(embed: discord.Embed, path: Path, size_bytes: int) -> None:
    """Populate ``embed`` with an inline image attachment or Markdown preview text."""
    if is_previewable_image(path, size_bytes):
        embed.set_image(url=f'attachment://preview{path.suffix.lower()}')
        return

    embed.description = build_file_preview_text(path, size_bytes)
