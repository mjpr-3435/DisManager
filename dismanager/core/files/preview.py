from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path
from typing import Any

MAX_IMAGE_PREVIEW_BYTES = 8 * 1024 * 1024

_IMAGE_EXTENSIONS = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.webp'})
_TAR_SUFFIXES = ('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')

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


def is_previewable_image(path: Path, size_bytes: int | None = None) -> bool:
    """Return whether ``path`` is an image small enough for inline preview."""
    if path.suffix.lower() not in _IMAGE_EXTENSIONS or not path.is_file():
        return False

    if size_bytes is None:
        try:
            size_bytes = path.stat(follow_symlinks=False).st_size
        except OSError:
            return False

    return size_bytes <= MAX_IMAGE_PREVIEW_BYTES


def build_file_preview_text(path: Path, size_bytes: int) -> str:
    """Build a Markdown preview snippet or ASCII archive tree for a non-image file."""
    if path.suffix.lower() in _IMAGE_EXTENSIONS:
        return '*(image too large to preview)*'

    name_lower = path.name.lower()
    if path.suffix.lower() == '.zip' or name_lower.endswith(_TAR_SUFFIXES):
        return _build_archive_preview(path)

    return _build_text_preview(path, size_bytes)


# =========================================
#            Internal Helpers
# =========================================


def _build_text_preview(path: Path, size_bytes: int) -> str:
    if size_bytes == 0:
        return '*(empty file)*'

    try:
        with path.open('rb') as fp:
            raw = fp.read(64 * 1024)
    except OSError as exc:
        return f'```\n{exc}```'

    if b'\x00' in raw:
        return '*(binary file — preview not available)*'

    text = _decode_utf8_prefix(raw, truncated=size_bytes > len(raw))
    if text is None:
        return '*(binary file — preview not available)*'

    lang = _CODE_LANG_BY_EXT.get(path.suffix.lower(), '')
    lines = text.splitlines()
    selected: list[str] = []
    total_chars = 0
    was_truncated = size_bytes > len(raw)

    for idx, line in enumerate(lines):
        if idx >= 30:
            was_truncated = True
            break
        remaining = 1800 - total_chars
        if remaining <= 0:
            was_truncated = True
            break
        if len(line) > remaining:
            selected.append(f'{line[:remaining]}...')
            was_truncated = True
            break
        selected.append(line)
        total_chars += len(line) + 1

    body = '\n'.join(selected).replace('```', '``\u200b`')
    suffix_note = '\n... (truncated)' if was_truncated else ''
    return f'```{lang}\n{body}{suffix_note}\n```'


def _decode_utf8_prefix(raw: bytes, *, truncated: bool) -> str | None:
    for trim in range(4 if truncated else 1):
        chunk = raw[: len(raw) - trim] if trim else raw
        if not chunk:
            return ''
        try:
            return chunk.decode('utf-8')
        except UnicodeDecodeError:
            continue
    return None


def _build_archive_preview(path: Path) -> str:
    try:
        entries = _read_archive_entries(path)
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
        return f'```\n{exc}```'

    if not entries:
        return '*(empty archive)*'

    tree: dict[str, Any] = {}
    for parts, is_dir in entries:
        _insert_tree_node(tree, parts, is_dir=is_dir)

    lines = [path.name]
    _render_ascii_tree(tree, prefix='', lines=lines)

    output_lines: list[str] = []
    char_count = 0
    truncated_entries = 0

    for idx, line in enumerate(lines):
        next_len = char_count + len(line) + 1
        if next_len > 3200 and idx > 1:
            truncated_entries = len(lines) - idx
            break
        output_lines.append(line)
        char_count = next_len

    if truncated_entries > 0:
        output_lines.append(f'... (+{truncated_entries} more entries)')

    body = '\n'.join(output_lines).replace('```', '``\u200b`')
    return f'```text\n{body}\n```'


def _read_archive_entries(path: Path) -> list[tuple[list[str], bool]]:
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as zf:
            return [
                (parts, info.is_dir())
                for info in zf.infolist()
                if (parts := [p for p in info.filename.strip('/').split('/') if p and p != '.'])
            ]

    with tarfile.open(path, 'r:*') as tf:
        return [
            (parts, member.isdir())
            for member in tf.getmembers()
            if (parts := [p for p in member.name.strip('/').split('/') if p and p != '.'])
        ]


def _insert_tree_node(root: dict[str, Any], parts: list[str], *, is_dir: bool) -> None:
    node = root
    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        existing = node.get(part)
        if is_last and not is_dir:
            if existing is None:
                node[part] = None
            return
        if not isinstance(existing, dict):
            existing = {}
            node[part] = existing
        node = existing


def _render_ascii_tree(node: dict[str, Any], *, prefix: str, lines: list[str]) -> None:
    items = sorted(node.items(), key=lambda item: (not isinstance(item[1], dict), item[0].lower()))
    last_idx = len(items) - 1
    for idx, (name, child) in enumerate(items):
        is_last = idx == last_idx
        connector = '`-- ' if is_last else '|-- '
        if isinstance(child, dict):
            lines.append(f'{prefix}{connector}{name}/')
            child_prefix = f'{prefix}{"    " if is_last else "|   "}'
            _render_ascii_tree(child, prefix=child_prefix, lines=lines)
        else:
            lines.append(f'{prefix}{connector}{name}')
