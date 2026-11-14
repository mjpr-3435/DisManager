from __future__ import annotations

import logging
import sys
from collections import deque
from datetime import datetime
from logging.handlers import BaseRotatingHandler
from pathlib import Path

from .paths import LOGS_DIR

MAX_SESSION_FILES = 20
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_MEMORY_BYTES = 8 * 1024 * 1024

_memory_handler: _MemoryRingHandler | None = None
_session_filename = 'dismanager.log'


def setup_logging() -> logging.Logger:
    """Configure session file logging (50 MB cap), 8 MB memory ring, and pre-connection console."""
    global _memory_handler, _session_filename

    logger = logging.getLogger('dismanager')
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _prune_old_sessions(LOGS_DIR, keep=MAX_SESSION_FILES - 1)

    session_path = _next_session_path(LOGS_DIR)
    _session_filename = session_path.name
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    file_handler = _CappedFileHandler(session_path, max_bytes=MAX_FILE_BYTES)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    memory_handler = _MemoryRingHandler(max_bytes=MAX_MEMORY_BYTES)
    memory_handler.setFormatter(formatter)
    _memory_handler = memory_handler
    logger.addHandler(memory_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(_ShortConsoleFormatter())
    logger.addHandler(console_handler)

    return logger


def mute_console_logging() -> None:
    """Silence console log handlers once Discord is connected and ready."""
    logger = logging.getLogger('dismanager')
    for handler in list(logger.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, (logging.FileHandler, BaseRotatingHandler)
        ):
            logger.removeHandler(handler)
            handler.close()


def get_recent_log_bytes() -> bytes:
    """Return up to the last 8 MB of logs from the current session."""
    if _memory_handler is None:
        return b''
    return _memory_handler.get_bytes()


def get_session_log_filename() -> str:
    """Return the filename of the current session's log."""
    return _session_filename


# =========================================
#            Internal Helpers
# =========================================


class _ShortConsoleFormatter(logging.Formatter):
    """Format console log records as a single clean line without tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return f'[{record.levelname}] {record.getMessage()}'


class _CappedFileHandler(logging.FileHandler):
    """FileHandler that stops writing once a hard byte limit is reached."""

    def __init__(self, filename: Path, *, max_bytes: int) -> None:
        super().__init__(filename, encoding='utf-8')
        self._max_bytes = max_bytes
        self._bytes_written = filename.stat().st_size if filename.exists() else 0
        self._capped = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._capped:
            return

        msg_bytes = (self.format(record) + self.terminator).encode('utf-8', errors='replace')
        if self._bytes_written + len(msg_bytes) > self._max_bytes:
            self._capped = True
            if self.stream is not None:
                self.stream.write(f'[LOG LIMIT REACHED: {self._max_bytes // (1024 * 1024)} MB]\n')
                self.stream.flush()
            return

        self._bytes_written += len(msg_bytes)
        super().emit(record)


class _MemoryRingHandler(logging.Handler):
    """In-memory ring buffer keeping the most recent log lines within max_bytes."""

    def __init__(self, *, max_bytes: int) -> None:
        super().__init__()
        self._max_bytes = max_bytes
        self._chunks: deque[bytes] = deque()
        self._total_bytes = 0

    def emit(self, record: logging.LogRecord) -> None:
        line = (self.format(record) + '\n').encode('utf-8', errors='replace')
        if len(line) > self._max_bytes:
            line = line[-self._max_bytes :]

        self._chunks.append(line)
        self._total_bytes += len(line)

        while self._total_bytes > self._max_bytes and self._chunks:
            removed = self._chunks.popleft()
            self._total_bytes -= len(removed)

    def get_bytes(self) -> bytes:
        self.acquire()
        try:
            return b''.join(self._chunks)
        finally:
            self.release()


def _next_session_path(logs_dir: Path) -> Path:
    stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    candidate = logs_dir / f'{stamp}.log'
    suffix = 1
    while candidate.exists():
        candidate = logs_dir / f'{stamp}_{suffix}.log'
        suffix += 1
    return candidate


def _prune_old_sessions(logs_dir: Path, *, keep: int) -> None:
    files = sorted(
        (p for p in logs_dir.glob('*.log') if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_file in files[keep:]:
        old_file.unlink(missing_ok=True)
