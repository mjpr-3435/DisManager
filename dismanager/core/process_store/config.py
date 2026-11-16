from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ProcessConfigError(Exception):
    """Raised when process configurations cannot be loaded, validated, or saved."""


@dataclass(frozen=True, slots=True)
class ProcessConfig:
    """Persisted configuration for a single managed process."""

    name: str
    start_command: str
    stop_command: str
    blacklist: tuple[str, ...]

    def resolve_path(self) -> Path:
        """Resolve the working directory path automatically from the process name."""
        return Path.cwd().resolve() / self.name
