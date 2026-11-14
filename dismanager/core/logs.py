from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from datetime import datetime
from logging.handlers import BaseRotatingHandler
from pathlib import Path

from .paths import LOGS_DIR

MAX_SESSION_FILES = 20
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_MEMORY_BYTES = 8 * 1024 * 1024

_memory_handler: _MemoryRingHandler | None = None
_session_filename = 'dismanager.log'


def setup_logging() -> logging.Logger:
    """Configure session file logging (25 MB cap), 8 MB memory ring, and pre-connection console."""
    global _memory_handler, _session_filename

    logger = logging.getLogger('dismanager')
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    session_writer = SessionLogWriter(LOGS_DIR, max_files=MAX_SESSION_FILES, max_bytes=MAX_FILE_BYTES)
    _session_filename = session_writer.path.name
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    file_handler = _CappedFileHandler(session_writer)
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


class SessionLogWriter:
    """Thread-safe rotating session log file capped at ``max_bytes`` with ``max_files`` retention."""

    def __init__(
        self,
        logs_dir: Path,
        *,
        max_files: int = MAX_SESSION_FILES,
        max_bytes: int = MAX_FILE_BYTES,
    ) -> None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        _prune_old_sessions(logs_dir, keep=max(0, max_files - 1))
        self.path = _next_session_path(logs_dir)
        self._max_bytes = max_bytes
        self._bytes_written = 0
        self._capped = False
        self._lock = threading.Lock()
        self._stream = self.path.open('a', encoding='utf-8')

    def write_line(self, line: str) -> None:
        text = line if line.endswith('\n') else f'{line}\n'
        msg_bytes = text.encode('utf-8', errors='replace')
        with self._lock:
            if self._capped or self._stream.closed:
                return
            if self._bytes_written + len(msg_bytes) > self._max_bytes:
                self._capped = True
                self._stream.write(f'[LOG LIMIT REACHED: {self._max_bytes // (1024 * 1024)} MB]\n')
                self._stream.flush()
                return
            self._bytes_written += len(msg_bytes)
            self._stream.write(text)
            self._stream.flush()

    def close(self) -> None:
        with self._lock:
            if not self._stream.closed:
                self._stream.close()


class _CappedFileHandler(logging.Handler):
    """Logging handler backed by a ``SessionLogWriter``."""

    def __init__(self, writer: SessionLogWriter) -> None:
        super().__init__()
        self._writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        self._writer.write_line(self.format(record))

    def close(self) -> None:
        self._writer.close()
        super().close()


class ByteRingBuffer:
    """Thread-safe in-memory ring buffer keeping the most recent lines within ``max_bytes``."""

    def __init__(self, *, max_bytes: int = MAX_MEMORY_BYTES) -> None:
        self._max_bytes = max_bytes
        self._chunks: deque[bytes] = deque()
        self._total_bytes = 0
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        chunk = (line + '\n').encode('utf-8', errors='replace')
        if len(chunk) > self._max_bytes:
            chunk = chunk[-self._max_bytes :]

        with self._lock:
            self._chunks.append(chunk)
            self._total_bytes += len(chunk)
            while self._total_bytes > self._max_bytes and self._chunks:
                removed = self._chunks.popleft()
                self._total_bytes -= len(removed)

    def get_bytes(self) -> bytes:
        with self._lock:
            return b''.join(self._chunks)

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._total_bytes = 0


class _MemoryRingHandler(logging.Handler):
    """Logging handler backed by a ``ByteRingBuffer``."""

    def __init__(self, *, max_bytes: int) -> None:
        super().__init__()
        self._buffer = ByteRingBuffer(max_bytes=max_bytes)

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append(self.format(record))

    def get_bytes(self) -> bytes:
        return self._buffer.get_bytes()


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
