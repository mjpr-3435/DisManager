from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..bootstrap.i18n import _
from .sandbox_paths import FileActionError, SandboxPaths

MAX_EDITABLE_TEXT_BYTES = 16 * 1024
MAX_EDITABLE_TEXT_CHARS = 4000


@dataclass(frozen=True, slots=True)
class TextSnippet:
    """Truncated UTF-8 text excerpt extracted from a file."""

    content: str
    suffix: str
    truncated: bool


def is_editable_text(path: Path) -> bool:
    """Return whether ``path`` is a UTF-8 text file fitting inside the edit limit."""
    try:
        if path.stat().st_size > MAX_EDITABLE_TEXT_BYTES:
            return False
        raw = path.read_bytes()
    except OSError:
        return False

    text = _decode_utf8(raw, allow_partial_tail=False)
    return text is not None and len(text) <= MAX_EDITABLE_TEXT_CHARS


def read_text_for_edit(path: Path) -> str:
    """Read a UTF-8 text file for editing, enforcing :data:`MAX_EDITABLE_TEXT_CHARS`."""
    try:
        content = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise FileActionError(_('✖ Could not read file: {}').format(exc)) from exc

    if len(content) > MAX_EDITABLE_TEXT_CHARS:
        raise FileActionError(_('✖ File exceeds the 4000-character modal limit.'))

    return content


def write_text_file(sandbox: SandboxPaths, path: Path, content: str) -> None:
    """Write ``content`` as UTF-8 to ``path`` inside ``sandbox``."""
    resolved = sandbox.require_within(path)
    try:
        resolved.write_text(content, encoding='utf-8')
    except OSError as exc:
        raise FileActionError(_('✖ Could not save file: {}').format(exc)) from exc


def extract_text_snippet(
    path: Path,
    size_bytes: int,
    *,
    max_bytes: int = 64 * 1024,
    max_lines: int = 30,
    max_chars: int = 1800,
) -> TextSnippet | Literal['empty', 'binary']:
    """Extract a bounded UTF-8 text snippet from ``path``, or classify it as empty/binary."""
    if size_bytes == 0:
        return 'empty'

    with path.open('rb') as fp:
        raw = fp.read(max_bytes)

    was_truncated = size_bytes > len(raw)
    text = _decode_utf8(raw, allow_partial_tail=was_truncated)
    if text is None:
        return 'binary'

    selected: list[str] = []
    total_chars = 0

    for idx, line in enumerate(text.splitlines()):
        if idx >= max_lines:
            was_truncated = True
            break
        remaining = max_chars - total_chars
        if remaining <= 0:
            was_truncated = True
            break
        if len(line) > remaining:
            selected.append(f'{line[:remaining]}...')
            was_truncated = True
            break
        selected.append(line)
        total_chars += len(line) + 1

    return TextSnippet(
        content='\n'.join(selected),
        suffix=path.suffix.lower(),
        truncated=was_truncated,
    )


# =========================================
#            Internal Helpers
# =========================================


def _decode_utf8(raw: bytes, *, allow_partial_tail: bool) -> str | None:
    if b'\x00' in raw:
        return None

    for trim in range(4 if allow_partial_tail else 1):
        chunk = raw[: len(raw) - trim] if trim else raw
        if not chunk:
            return ''
        try:
            return chunk.decode('utf-8')
        except UnicodeDecodeError:
            continue
    return None
