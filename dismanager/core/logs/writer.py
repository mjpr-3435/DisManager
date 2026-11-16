from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

_MAX_SESSION_FILES = 20
_MAX_FILE_BYTES = 25 * 1024 * 1024


class SessionLogWriter:
    """Thread-safe rotating session log file capped at 25 MB with 20-session retention."""

    def __init__(self, logs_dir: Path) -> None:
        # Ensure the directory exists before pruning old sessions or opening the new file.
        logs_dir.mkdir(parents=True, exist_ok=True)
        # Leave room for the new session file opened below (19 old + 1 new = 20).
        _prune_old_sessions(logs_dir, keep=_MAX_SESSION_FILES - 1)
        self.path = _next_session_path(logs_dir)
        self._bytes_written = 0
        self._capped = False
        # Lock because multiple threads (asyncio, process reader, discord) may log concurrently.
        self._lock = threading.Lock()
        self._stream = self.path.open('a', encoding='utf-8')

    def write_line(self, line: str) -> None:
        # Normalize newline and measure actual UTF-8 byte length to enforce the 25 MB cap.
        text = line if line.endswith('\n') else f'{line}\n'
        msg_bytes = text.encode('utf-8', errors='replace')

        with self._lock:
            if self._capped or self._stream.closed:
                return

            # If this line exceeds the cap, write a final notice and stop further writes.
            if self._bytes_written + len(msg_bytes) > _MAX_FILE_BYTES:
                self._capped = True
                self._stream.write(f'[LOG LIMIT REACHED: {_MAX_FILE_BYTES // (1024 * 1024)} MB]\n')
                self._stream.flush()
                return

            self._bytes_written += len(msg_bytes)
            self._stream.write(text)
            # Flush immediately so recent lines are not lost on an abrupt exit.
            self._stream.flush()

    def close(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.close()


# =========================================
#            Internal Helpers
# =========================================


def _prune_old_sessions(logs_dir: Path, *, keep: int) -> None:
    files = sorted(
        (p for p in logs_dir.glob('*.log') if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_file in files[keep:]:
        old_file.unlink(missing_ok=True)


def _next_session_path(logs_dir: Path) -> Path:
    stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return logs_dir / f'{stamp}.log'
