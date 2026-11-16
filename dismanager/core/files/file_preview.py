from __future__ import annotations

import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .archive_operations import build_archive_tree_text, is_archive_file
from .text_files import extract_text_snippet

MAX_IMAGE_PREVIEW_BYTES = 8 * 1024 * 1024

_IMAGE_EXTENSIONS = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.webp'})

UnavailableReason = Literal['image_too_large', 'empty_file', 'empty_archive', 'binary_file', 'read_error']


@dataclass(frozen=True, slots=True)
class ImagePreview:
    """File is an image suitable for inline attachment preview."""

    suffix: str


@dataclass(frozen=True, slots=True)
class TextPreview:
    """Plain UTF-8 text snippet extracted from a file."""

    content: str
    suffix: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class ArchivePreview:
    """ASCII tree text rendered from a compressed archive."""

    tree_text: str


@dataclass(frozen=True, slots=True)
class PreviewUnavailable:
    """Structured reason explaining why a file cannot be previewed."""

    reason: UnavailableReason
    detail: str | None = None


FilePreview = ImagePreview | TextPreview | ArchivePreview | PreviewUnavailable


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


def inspect_file_preview(path: Path, size_bytes: int) -> FilePreview:
    """Inspect ``path`` and return a structured preview result without UI formatting."""
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTENSIONS:
        if size_bytes <= MAX_IMAGE_PREVIEW_BYTES:
            return ImagePreview(suffix=suffix)
        return PreviewUnavailable(reason='image_too_large')

    if is_archive_file(path):
        try:
            tree_text = build_archive_tree_text(path)
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
            return PreviewUnavailable(reason='read_error', detail=str(exc))

        if tree_text is None:
            return PreviewUnavailable(reason='empty_archive')
        return ArchivePreview(tree_text=tree_text)

    try:
        snippet = extract_text_snippet(path, size_bytes)
    except OSError as exc:
        return PreviewUnavailable(reason='read_error', detail=str(exc))

    if snippet == 'empty':
        return PreviewUnavailable(reason='empty_file')
    if snippet == 'binary':
        return PreviewUnavailable(reason='binary_file')
    return TextPreview(content=snippet.content, suffix=snippet.suffix, truncated=snippet.truncated)
