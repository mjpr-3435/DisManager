from __future__ import annotations

from pathlib import Path

import discord

from ....core.files import (
    ArchivePreview,
    ImagePreview,
    PreviewUnavailable,
    TextPreview,
    inspect_file_preview,
    is_previewable_image,
)

_CODE_LANG_BY_EXT: dict[str, str] = {
    '.bat': 'bat',
    '.cfg': 'ini',
    '.cmd': 'bat',
    '.conf': 'ini',
    '.css': 'css',
    '.env': 'ini',
    '.html': 'html',
    '.ini': 'ini',
    '.js': 'js',
    '.json': 'json',
    '.log': 'log',
    '.mcmeta': 'json',
    '.md': 'md',
    '.properties': 'ini',
    '.ps1': 'ps1',
    '.py': 'py',
    '.sh': 'sh',
    '.sql': 'sql',
    '.toml': 'toml',
    '.ts': 'ts',
    '.txt': 'text',
    '.xml': 'xml',
    '.yaml': 'yaml',
    '.yml': 'yaml',
}

_UNAVAILABLE_MESSAGES: dict[str, str] = {
    'image_too_large': '*(image too large to preview)*',
    'empty_file': '*(empty file)*',
    'empty_archive': '*(empty archive)*',
    'binary_file': '*(binary file — preview not available)*',
}


def build_file_attachment(path: Path) -> discord.File | None:
    """Return a Discord attachment if ``path`` is a previewable image."""
    if not is_previewable_image(path):
        return None
    return discord.File(path, filename=f'preview{path.suffix.lower()}')


def populate_file_preview(embed: discord.Embed, path: Path, size_bytes: int) -> None:
    """Populate ``embed`` with an inline image attachment or formatted Markdown preview."""
    preview = inspect_file_preview(path, size_bytes)
    if isinstance(preview, ImagePreview):
        embed.set_image(url=f'attachment://preview{preview.suffix}')
        return

    if isinstance(preview, ArchivePreview):
        embed.description = _format_code_block('text', preview.tree_text)
        return

    if isinstance(preview, TextPreview):
        lang = _CODE_LANG_BY_EXT.get(preview.suffix, '')
        suffix_note = '\n... (truncated)' if preview.truncated else ''
        embed.description = _format_code_block(lang, f'{preview.content}{suffix_note}')
        return

    embed.description = _format_unavailable(preview)


# =========================================
#            Internal Helpers
# =========================================


def _format_code_block(lang: str, body: str) -> str:
    escaped = body.replace('```', '``\u200b`')
    return f'```{lang}\n{escaped}\n```'


def _format_unavailable(preview: PreviewUnavailable) -> str:
    if preview.reason == 'read_error':
        return f'```\n{preview.detail or "Read error"}```'
    return _UNAVAILABLE_MESSAGES[preview.reason]
