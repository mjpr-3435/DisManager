from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shlex
import subprocess
import threading
from collections.abc import Callable
from typing import Any

import psutil

from ...bootstrap.paths import LOGS_DIR
from ...logs import ByteRingBuffer, SessionLogWriter
from ...process_store import ProcessConfig, ProcessConfigError

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')


class ProcessRunner:
    """Low-level OS subprocess runner with ANSI stripping, log buffering, and process-tree control."""

    def __init__(
        self,
        config: ProcessConfig,
        *,
        on_line: Callable[[str], None],
        on_exit: Callable[[str | None, bool], None],
    ) -> None:
        self._config = config
        self._on_line = on_line
        self._on_exit = on_exit
        self._process: subprocess.Popen[bytes] | None = None
        self._log_buffer = ByteRingBuffer()
        self._stop_requested = False
        self._reader_thread: threading.Thread | None = None

    # --- Internal Behaviour ---

    def _read_output(
        self,
        proc: subprocess.Popen[bytes],
        session_log: SessionLogWriter,
        loop: asyncio.AbstractEventLoop | None,
    ) -> None:
        stdout = proc.stdout
        try:
            if stdout is not None:
                try:
                    for raw_line in iter(stdout.readline, b''):
                        decoded = raw_line.decode('utf-8', errors='replace').rstrip('\r\n')
                        cleaned = _ANSI_ESCAPE_RE.sub('', decoded)
                        if not cleaned.strip():
                            continue
                        if any(term in cleaned for term in self._config.blacklist):
                            continue
                        self._log_buffer.append(cleaned)
                        session_log.write_line(cleaned)
                        if loop is not None and not loop.is_closed():
                            loop.call_soon_threadsafe(self._on_line, cleaned)
                finally:
                    with contextlib.suppress(OSError):
                        stdout.close()
        finally:
            session_log.close()

        returncode = proc.wait()
        stop_requested = self._stop_requested
        if self._process is proc:
            self._process = None
            self._stop_requested = False

        if loop is not None and not loop.is_closed():
            crashed = not stop_requested and returncode != 0
            reason = f'Process exited unexpectedly (code {returncode}).' if crashed else None
            loop.call_soon_threadsafe(self._on_exit, reason, crashed)

    # --- Internal API ---

    @property
    def is_alive(self) -> bool:
        """Return ``True`` while the underlying OS subprocess is still running."""
        return self._process is not None and self._process.poll() is None

    def update_config(self, config: ProcessConfig) -> None:
        """Update the active process configuration."""
        self._config = config

    def recent_log_bytes(self) -> bytes:
        """Return the buffered recent output bytes."""
        return self._log_buffer.get_bytes()

    def start(self) -> asyncio.AbstractEventLoop | None:
        """Spawn the configured subprocess, start output reading, and return the active loop."""
        raw_cmd = self._config.start_command.strip()
        if not raw_cmd:
            raise ProcessConfigError(f"Process '{self._config.name}' has an empty start command.")

        args = (
            shlex.split(raw_cmd, posix=True)
            if os.name != 'nt'
            else [
                token[1:-1]
                if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
                else token
                for token in shlex.split(raw_cmd, posix=False)
            ]
        )
        if not args:
            raise ProcessConfigError(f"Process '{self._config.name}' has an invalid start command.")

        cwd = self._config.resolve_path()
        cwd.mkdir(parents=True, exist_ok=True)

        self._log_buffer.clear()
        self._stop_requested = False

        popen_kwargs: dict[str, Any] = {
            'cwd': cwd,
            'stdin': subprocess.PIPE,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.STDOUT,
        }
        if os.name == 'nt':
            popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs['start_new_session'] = True

        try:
            proc = subprocess.Popen(args, **popen_kwargs)
        except OSError as exc:
            raise ProcessConfigError(f"Could not start '{self._config.name}': {exc}") from exc

        self._process = proc
        session_log = SessionLogWriter(LOGS_DIR / 'processes' / self._config.name)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        self._reader_thread = threading.Thread(
            target=self._read_output,
            args=(proc, session_log, loop),
            name=f'process-reader-{self._config.name}',
            daemon=True,
        )
        self._reader_thread.start()
        return loop

    def mark_stop_requested(self) -> bool:
        """Mark the process as intentionally stopping; return ``True`` on the first stop signal."""
        first_signal = not self._stop_requested
        self._stop_requested = True
        return first_signal

    def execute(self, command: str) -> bool:
        """Write a command line to the subprocess stdin."""
        proc = self._process
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False

        try:
            proc.stdin.write(f'{command}\n'.encode())
            proc.stdin.flush()
            return True
        except OSError:
            return False

    def kill_tree(self) -> bool:
        """Forcefully terminate the process and all of its child processes."""
        proc = self._process
        if proc is None:
            return False

        with contextlib.suppress(psutil.Error, OSError):
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.Error, OSError):
                    child.kill()
            parent.kill()

        with contextlib.suppress(OSError):
            proc.kill()
        return True

    def ram_usage_bytes(self) -> int:
        """Return total RSS memory in bytes for the process tree."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return 0

        try:
            parent = psutil.Process(proc.pid)
            total = int(parent.memory_info().rss)
            for child in parent.children(recursive=True):
                with contextlib.suppress(psutil.Error):
                    total += int(child.memory_info().rss)
            return total
        except psutil.Error:
            return 0
