from __future__ import annotations

import logging
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .paths import LOGS_DIR

_MAX_SESSION_FILES  = 20
_MAX_FILE_BYTES     = 25 * 1024 * 1024
_MAX_MEMORY_BYTES   = 8 * 1024 * 1024


class LogSession:
    """Active logging session for a single DisManager execution."""

    _console_handler: logging.StreamHandler[TextIO] | None

    def __init__(self) -> None:
        console_handler         = logging.StreamHandler(sys.stderr)
        self._writer            = _SessionLogWriter(LOGS_DIR)
        self._file_handler      = _CappedFileHandler(self._writer)
        self._memory_handler    = _MemoryRingHandler()
        self._console_handler   = console_handler
        self._dismanager_logger = logging.getLogger('dismanager')
        self._discord_logger    = logging.getLogger('discord')
        self._attach_handlers(console_handler)

    def _attach_handlers(self, console_handler: logging.StreamHandler[TextIO]) -> None:
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
        self._file_handler.setFormatter(formatter)
        self._memory_handler.setFormatter(formatter)

        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(_ShortConsoleFormatter())

        self._dismanager_logger.setLevel(logging.INFO)
        self._dismanager_logger.propagate = False
        self._dismanager_logger.addHandler(self._file_handler)
        self._dismanager_logger.addHandler(self._memory_handler)
        self._dismanager_logger.addHandler(console_handler)

        self._discord_logger.setLevel(logging.WARNING)
        self._discord_logger.propagate = False
        self._discord_logger.addHandler(self._file_handler)
        self._discord_logger.addHandler(self._memory_handler)

    @property
    def filename(self) -> str:
        """Return the active session log filename."""
        return self._writer.path.name

    def recent_bytes(self) -> bytes:
        """Return up to the last 8 MB of formatted log records from this session."""
        return self._memory_handler.get_bytes()

    def mute_console(self) -> None:
        """Detach and close the temporary startup console handler once the UI is ready."""
        if self._console_handler is None:
            return
        self._dismanager_logger.removeHandler(self._console_handler)
        self._console_handler.close()
        self._console_handler = None

    def close(self) -> None:
        """Detach all session handlers from loggers and close underlying streams."""
        self.mute_console()
        for logger in (self._dismanager_logger, self._discord_logger):
            logger.removeHandler(self._file_handler)
            logger.removeHandler(self._memory_handler)
        self._file_handler.close()
        self._memory_handler.close()


# =========================================
#            Internal Helpers
# =========================================


# ---------------------------------------------------------------------------
# 1. Disk File Layer (Handler -> Writer -> Rotation)
# ---------------------------------------------------------------------------


class _CappedFileHandler(logging.Handler):
    """Logging handler adapter that delegates each record to the disk writer."""

    def __init__(self, writer: _SessionLogWriter) -> None:
        super().__init__()
        self._writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        # Format the LogRecord (timestamp, level, module, message/traceback) and write it to disk.
        self._writer.write_line(self.format(record))

    def close(self) -> None:
        # Close the underlying file first, then release the handler from logging.
        self._writer.close()
        super().close()


class _SessionLogWriter:
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


# ---------------------------------------------------------------------------
# 2. RAM Buffer Layer (Handler -> 8 MB RingBuffer for !!log)
# ---------------------------------------------------------------------------


class _MemoryRingHandler(logging.Handler):
    """Logging handler adapter that keeps the most recent 8 MB of logs in RAM."""

    def __init__(self) -> None:
        super().__init__()
        self._buffer = _ByteRingBuffer()

    def emit(self, record: logging.LogRecord) -> None:
        # Store the formatted line in the in-memory ring buffer.
        self._buffer.append(self.format(record))

    def get_bytes(self) -> bytes:
        return self._buffer.get_bytes()


class _ByteRingBuffer:
    """Thread-safe in-memory ring buffer that drops oldest lines past 8 MB."""

    def __init__(self) -> None:
        # deque supports O(1) popleft() when evicting old chunks at capacity.
        self._chunks: deque[bytes] = deque()
        self._total_bytes = 0
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        chunk = (line + '\n').encode('utf-8', errors='replace')
        # If a single oversized line exceeds 8 MB, keep only its trailing 8 MB.
        if len(chunk) > _MAX_MEMORY_BYTES:
            chunk = chunk[-_MAX_MEMORY_BYTES:]

        with self._lock:
            self._chunks.append(chunk)
            self._total_bytes += len(chunk)
            # Drop oldest lines until total buffered size is back within the limit.
            while self._total_bytes > _MAX_MEMORY_BYTES and self._chunks:
                removed = self._chunks.popleft()
                self._total_bytes -= len(removed)

    def get_bytes(self) -> bytes:
        # Join all buffered chunks into a single bytes payload ready to upload.
        with self._lock:
            return b''.join(self._chunks)

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._total_bytes = 0


# ---------------------------------------------------------------------------
# 3. Console Formatter and Session File Helpers
# ---------------------------------------------------------------------------


class _ShortConsoleFormatter(logging.Formatter):
    """Format console log records as a single clean line without tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return f'[{record.levelname}] {record.getMessage()}'


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
