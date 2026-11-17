from __future__ import annotations

import threading
from collections import deque

_MAX_MEMORY_BYTES = 8 * 1024 * 1024


class ByteRingBuffer:
    """Thread-safe in-memory ring buffer that drops oldest lines past 8 MB."""

    def __init__(self) -> None:
        # deque supports O(1) popleft() when evicting old chunks at capacity.
        self._chunks: deque[bytes] = deque()
        self._total_bytes = 0
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        """Append a UTF-8 line to the buffer, evicting oldest entries past 8 MB."""
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
        """Return all currently buffered log lines concatenated as bytes."""
        # Join all buffered chunks into a single bytes payload ready to upload.
        with self._lock:
            return b''.join(self._chunks)

    def clear(self) -> None:
        """Discard all buffered log chunks and reset the byte counter."""
        with self._lock:
            self._chunks.clear()
            self._total_bytes = 0
