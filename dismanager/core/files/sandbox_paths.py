from __future__ import annotations

from pathlib import Path

from ..bootstrap.i18n import _


class FileActionError(Exception):
    """Raised when a file or directory operation fails validation, confinement, or I/O."""


class SandboxPaths:
    """Confines filesystem paths and ``DisManager/...`` virtual paths within a root directory."""

    root: Path
    virtual_root: str

    def __init__(self, root: Path, *, virtual_root: str = 'DisManager') -> None:
        self.root = root.resolve()
        self.virtual_root = virtual_root

    # --- Public API ---

    def clamp(self, path: Path) -> Path:
        """Resolve ``path`` and fall back to ``root`` if it escapes the sandbox."""
        resolved = path.resolve()
        return resolved if resolved.is_relative_to(self.root) else self.root

    def is_root(self, path: Path) -> bool:
        """Return whether ``path`` resolves to the sandbox root directory."""
        return path.resolve() == self.root

    def is_within(self, path: Path) -> bool:
        """Return whether ``path`` resolves inside the sandbox root."""
        return path.resolve().is_relative_to(self.root)

    def require_within(self, path: Path, *, error_message: str | None = None) -> Path:
        """Resolve ``path`` and ensure it stays inside ``root``."""
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise FileActionError(error_message or _('✖ Invalid file path.'))
        return resolved

    def require_mutable(self, path: Path, *, root_error: str) -> Path:
        """Resolve ``path`` and ensure it is a mutable entry strictly inside ``root``."""
        resolved = self.require_within(path, error_message=root_error)
        if resolved == self.root:
            raise FileActionError(root_error)
        return resolved

    def to_virtual(self, path: Path) -> str:
        """Format ``path`` under ``root`` using the virtual root prefix."""
        resolved = path.resolve()
        if resolved == self.root:
            return self.virtual_root

        rel = resolved.relative_to(self.root)
        return f'{self.virtual_root}/{rel.as_posix()}'

    def resolve_virtual(self, raw_path: str) -> Path | None:
        """Resolve a user-supplied virtual path if it exists inside ``root``."""
        cleaned = raw_path.strip().replace('\\', '/')
        parts = [part for part in cleaned.split('/') if part]
        if not parts or parts[0] != self.virtual_root:
            return None

        candidate = self.root.joinpath(*parts[1:]).resolve()
        if not candidate.is_relative_to(self.root) or not candidate.exists():
            return None
        return candidate

    def resolve_new_child(
        self,
        parent: Path,
        raw_name: str,
        *,
        invalid_message: str,
    ) -> Path:
        """Validate ``raw_name`` as a direct child of ``parent`` inside ``root``."""
        target_dir = self.require_within(parent, error_message=_('✖ Invalid directory path.'))
        name = raw_name.strip()
        dest = (target_dir / name).resolve()
        if not is_valid_entry_name(name) or dest.parent != target_dir:
            raise FileActionError(invalid_message)
        if dest.exists():
            raise FileActionError(_('✖ `{}` already exists.').format(name))
        return dest

    def resolve_rename_target(self, target: Path, raw_new_name: str) -> tuple[Path, Path]:
        """Resolve ``target`` and validate ``raw_new_name`` as a sibling destination."""
        resolved = self.require_mutable(
            target,
            root_error=_('✖ You cannot rename the root `DisManager` directory.'),
        )
        new_name = raw_new_name.strip()
        if new_name == resolved.name:
            return resolved, resolved

        dest = (resolved.parent / new_name).resolve()
        if not is_valid_entry_name(new_name) or dest.parent != resolved.parent:
            raise FileActionError(_('✖ Invalid name.'))
        if dest.exists():
            raise FileActionError(_('✖ `{}` already exists.').format(new_name))
        return resolved, dest

    def resolve_upload(self, raw_filename: str, target_dir: Path) -> Path | None:
        """Validate an uploaded attachment name and return its path under ``target_dir``."""
        resolved_dir = target_dir.resolve()
        if not resolved_dir.is_relative_to(self.root):
            return None

        filename = Path(raw_filename).name
        dest = (resolved_dir / filename).resolve()
        if not filename or not dest.is_relative_to(resolved_dir):
            return None
        return dest


def is_valid_entry_name(name: str) -> bool:
    """Return whether ``name`` is a valid single directory or file name."""
    return bool(name) and name not in {'.', '..'} and not any(ch in name for ch in '<>:"/\\|?*')
