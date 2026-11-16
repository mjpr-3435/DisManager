from __future__ import annotations

from pathlib import Path

from ..bootstrap.i18n import _
from .tree import remove_path

MAX_EDITABLE_TEXT_BYTES = 16 * 1024
MAX_EDITABLE_TEXT_CHARS = 4000


class FileActionError(Exception):
    """Raised when a file or directory operation fails validation or I/O."""


def clamp_to_root(path: Path, root: Path) -> Path:
    """Resolve ``path`` and fall back to ``root`` if it escapes the allowed tree."""
    resolved_root = root.resolve()
    resolved = path.resolve()
    return resolved if resolved.is_relative_to(resolved_root) else resolved_root


def to_dismanager_path(path: Path, root: Path) -> str:
    """Format a filesystem path under ``root`` with the ``DisManager`` mask."""
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved == resolved_root:
        return 'DisManager'

    rel = resolved.relative_to(resolved_root)
    return f'DisManager/{rel.as_posix()}'


def is_valid_entry_name(name: str) -> bool:
    """Return whether ``name`` is a valid single directory or file name."""
    return bool(name) and name not in {'.', '..'} and not any(ch in name for ch in '<>:"/\\|?*')


def resolve_dismanager_path(raw_path: str, root: Path) -> Path | None:
    """Resolve a user-supplied ``DisManager/...`` path if it exists inside ``root``."""
    resolved_root = root.resolve()
    cleaned = raw_path.strip().replace('\\', '/')
    parts = [part for part in cleaned.split('/') if part]
    if not parts or parts[0] != 'DisManager':
        return None

    candidate = resolved_root.joinpath(*parts[1:]).resolve()
    if not candidate.is_relative_to(resolved_root) or not candidate.exists():
        return None
    return candidate


def resolve_upload_path(raw_filename: str, target_dir: Path, root: Path) -> Path | None:
    """Validate an uploaded attachment name and return its destination path under ``target_dir``."""
    resolved_root = root.resolve()
    resolved_dir = target_dir.resolve()
    if not resolved_dir.is_relative_to(resolved_root):
        return None

    filename = Path(raw_filename).name
    dest = (resolved_dir / filename).resolve()
    if not filename or not dest.is_relative_to(resolved_dir):
        return None
    return dest


def list_directory_entries(path: Path) -> tuple[list[Path], list[Path]]:
    """Return sorted ``(dirs, files)`` entries inside ``path``."""
    entries = sorted(path.iterdir(), key=lambda entry: entry.name.lower())
    dirs = [entry for entry in entries if entry.is_dir()]
    files = [entry for entry in entries if entry.is_file()]
    return dirs, files


def get_sibling_files(path: Path) -> tuple[list[Path], int] | None:
    """Return ``(sibling_files, index)`` for ``path`` inside its parent directory."""
    try:
        _, files = list_directory_entries(path.parent)
        return files, files.index(path)
    except (OSError, ValueError):
        return None


def create_directory(parent: Path, root: Path, raw_name: str) -> Path:
    """Create a validated subdirectory under ``parent`` within ``root``."""
    resolved_root = root.resolve()
    target_dir = parent.resolve()
    if not target_dir.is_relative_to(resolved_root):
        raise FileActionError(_('✖ Invalid directory path.'))

    name = raw_name.strip()
    dest = (target_dir / name).resolve()
    if not is_valid_entry_name(name) or dest.parent != target_dir:
        raise FileActionError(_('✖ Invalid directory name.'))

    if dest.exists():
        raise FileActionError(_('✖ `{}` already exists.').format(name))

    try:
        dest.mkdir()
    except OSError as exc:
        raise FileActionError(_('✖ Could not create directory: {}').format(exc)) from exc

    return dest


def rename_entry(target: Path, root: Path, raw_new_name: str) -> Path:
    """Rename a directory or file under ``root`` and return its new path."""
    resolved_root = root.resolve()
    resolved = target.resolve()
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        raise FileActionError(_('✖ You cannot rename the root `DisManager` directory.'))

    new_name = raw_new_name.strip()
    if new_name == resolved.name:
        return resolved

    dest = (resolved.parent / new_name).resolve()
    if not is_valid_entry_name(new_name) or dest.parent != resolved.parent:
        raise FileActionError(_('✖ Invalid name.'))

    if dest.exists():
        raise FileActionError(_('✖ `{}` already exists.').format(new_name))

    try:
        resolved.rename(dest)
    except OSError as exc:
        raise FileActionError(_('✖ Could not rename: {}').format(exc)) from exc

    return dest


def delete_entry(target: Path, root: Path) -> None:
    """Delete a file or directory under ``root``."""
    resolved_root = root.resolve()
    resolved = target.resolve()
    if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
        raise FileActionError(_('✖ You cannot delete the root `DisManager` directory.'))

    try:
        remove_path(resolved)
    except OSError as exc:
        raise FileActionError(_('✖ Could not delete `{}`: {}').format(resolved.name, exc)) from exc


def read_file_size(path: Path) -> int:
    """Return the byte size of ``path`` or raise :class:`FileActionError`."""
    try:
        return path.stat().st_size
    except OSError as exc:
        raise FileActionError(_('✖ Could not read file: {}').format(exc)) from exc


def is_editable_text(path: Path) -> bool:
    """Return whether ``path`` is a UTF-8 text file fitting inside the edit limit."""
    try:
        if path.stat().st_size > MAX_EDITABLE_TEXT_BYTES:
            return False
        raw = path.read_bytes()
    except OSError:
        return False

    if b'\x00' in raw:
        return False

    try:
        return len(raw.decode('utf-8')) <= MAX_EDITABLE_TEXT_CHARS
    except UnicodeDecodeError:
        return False


def read_text_for_edit(path: Path) -> str:
    """Read a UTF-8 text file for editing, enforcing :data:`MAX_EDITABLE_TEXT_CHARS`."""
    try:
        content = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise FileActionError(_('✖ Could not read file: {}').format(exc)) from exc

    if len(content) > MAX_EDITABLE_TEXT_CHARS:
        raise FileActionError(_('✖ File exceeds the 4000-character modal limit.'))

    return content


def write_text_file(path: Path, root: Path, content: str) -> None:
    """Write ``content`` as UTF-8 to ``path`` inside ``root``."""
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise FileActionError(_('✖ Invalid file path.'))

    try:
        resolved.write_text(content, encoding='utf-8')
    except OSError as exc:
        raise FileActionError(_('✖ Could not save file: {}').format(exc)) from exc
