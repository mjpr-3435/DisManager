from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ...bootstrap.paths import LOGS_DIR
from ...logs import ByteRingBuffer, SessionLogWriter

if TYPE_CHECKING:
    from ..process import ManagedProcess

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')


class ProcessLogger:
    """Manages ANSI stripping, 8 MB RAM buffering, and session log files."""

    _session_log: SessionLogWriter | None

    def __init__(self, process: ManagedProcess) -> None:
        self._process = process
        self._buffer = ByteRingBuffer()
        self._session_log = None

    # --- Internal API ---

    def start_session(self) -> None:
        """Clear the recent RAM buffer and open a new rotating session log file."""
        self.close_session()
        self._buffer.clear()
        self._session_log = SessionLogWriter(LOGS_DIR / 'processes' / self._process.name)

    def record_line(self, raw_line: str) -> str | None:
        """Strip ANSI codes and persist a decoded stdout line; return ``None`` if blank."""
        cleaned = _ANSI_ESCAPE_RE.sub('', raw_line)
        if not cleaned.strip():
            return None

        self._buffer.append(cleaned)
        if self._session_log is not None:
            self._session_log.write_line(cleaned)
        return cleaned

    def close_session(self) -> None:
        """Close the active session log file, if open."""
        if self._session_log is not None:
            self._session_log.close()
            self._session_log = None

    def recent_bytes(self) -> bytes:
        """Return the buffered recent output bytes."""
        return self._buffer.get_bytes()

    def last_lines(self, *, limit: int = 40) -> list[str]:
        """Return up to the last ``limit`` lines from the recent 8 MB buffer."""
        if limit <= 0:
            return []
        raw = self._buffer.get_bytes()
        if not raw:
            return []
        return raw.decode('utf-8', errors='replace').splitlines()[-limit:]
