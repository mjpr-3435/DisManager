from __future__ import annotations

import logging
import sys
from typing import TextIO

from ..logs import ByteRingBuffer, SessionLogWriter
from .paths import LOGS_DIR


class LogSession:
    """Active logging session for a single DisManager execution."""

    _console_handler: logging.StreamHandler[TextIO] | None

    def __init__(self) -> None:
        console_handler         = logging.StreamHandler(sys.stderr)
        self._writer            = SessionLogWriter(LOGS_DIR)
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


class _CappedFileHandler(logging.Handler):
    """Logging handler adapter that delegates each record to the disk writer."""

    def __init__(self, writer: SessionLogWriter) -> None:
        super().__init__()
        self._writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        # Format the LogRecord (timestamp, level, module, message/traceback) and write it to disk.
        self._writer.write_line(self.format(record))

    def close(self) -> None:
        # Close the underlying file first, then release the handler from logging.
        self._writer.close()
        super().close()


class _MemoryRingHandler(logging.Handler):
    """Logging handler adapter that keeps the most recent 8 MB of logs in RAM."""

    def __init__(self) -> None:
        super().__init__()
        self._buffer = ByteRingBuffer()

    def emit(self, record: logging.LogRecord) -> None:
        # Store the formatted line in the in-memory ring buffer.
        self._buffer.append(self.format(record))

    def get_bytes(self) -> bytes:
        return self._buffer.get_bytes()


class _ShortConsoleFormatter(logging.Formatter):
    """Format console log records as a single clean line without tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return f'[{record.levelname}] {record.getMessage()}'
