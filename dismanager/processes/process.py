from __future__ import annotations

import asyncio
import contextlib
import os
import re
import shlex
import signal
import subprocess
import threading
from typing import TYPE_CHECKING, Any

import psutil

from ..core.logs import ByteRingBuffer, SessionLogWriter
from ..core.paths import LOGS_DIR
from ..core.processes import ProcessConfig, ProcessConfigError
from .relay import ConsoleRelay

if TYPE_CHECKING:
    from ..discord.client import DisManagerClient

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')


class ManagedProcess:
    """Cross-platform subprocess runner with ANSI stripping, blacklist filtering, and 8 MB log buffer."""

    def __init__(self, config: ProcessConfig, client: DisManagerClient) -> None:
        self._config = config
        self._relay = ConsoleRelay(config.name, client)
        self._process: subprocess.Popen[bytes] | None = None
        self._log_buffer = ByteRingBuffer()
        self._stop_requested = False
        self._reader_thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return self._config.name

    def update_config(self, config: ProcessConfig) -> None:
        """Update process configuration in-place."""
        self._config = config

    def is_running(self) -> bool:
        """Return ``True`` while the subprocess is alive or its Discord relay is still draining."""
        return self._is_process_alive() or self._relay.is_active

    def start(self) -> bool:
        """Start the configured subprocess and begin reading its output."""
        if self.is_running():
            return False

        raw_cmd = self._config.start_command.strip()
        if not raw_cmd:
            raise ProcessConfigError(f"Process '{self.name}' has an empty start command.")

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
            raise ProcessConfigError(f"Process '{self.name}' has an invalid start command.")

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
            raise ProcessConfigError(f"Could not start '{self.name}': {exc}") from exc

        self._relay.start()

        self._process = proc
        session_log = SessionLogWriter(LOGS_DIR / 'processes' / self.name)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._reader_thread = threading.Thread(
            target=self._read_output,
            args=(proc, session_log, loop),
            name=f'process-reader-{self.name}',
            daemon=True,
        )
        self._reader_thread.start()
        return True

    def stop(self) -> bool:
        """Request a graceful stop via ``stop_command`` or OS signal."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return False

        self._stop_requested = True
        if self._config.stop_command:
            return self.execute(self._config.stop_command)

        with contextlib.suppress(OSError):
            if os.name == 'nt':
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)
        return True

    def kill(self) -> bool:
        """Forcefully terminate the process and all of its child processes."""
        proc = self._process
        if proc is None:
            return False

        self._stop_requested = True
        with contextlib.suppress(psutil.Error, OSError):
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                with contextlib.suppress(psutil.Error, OSError):
                    child.kill()
            parent.kill()

        with contextlib.suppress(OSError):
            proc.kill()
        return True

    async def restart(self) -> bool:
        """Stop the process cleanly, wait for exit and relay drain, and start it again."""
        if self.is_running():
            if self._is_process_alive():
                self.stop()
                deadline = asyncio.get_running_loop().time() + 30.0
                while self._is_process_alive() and asyncio.get_running_loop().time() < deadline:
                    await asyncio.sleep(0.1)
                if self._is_process_alive():
                    self.kill()
                    await asyncio.sleep(0.2)
            await self._relay.shutdown()

        return self.start()

    async def send_logs(self) -> None:
        """Send this process's recent 8 MB log buffer to its Discord console thread."""
        await self._relay.send_log_file(self._log_buffer.get_bytes())

    async def shutdown(self) -> None:
        """Stop the subprocess gracefully, force-kill after 60 s, and drain its Discord relay."""
        if self._is_process_alive():
            self.stop()
            deadline = asyncio.get_running_loop().time() + 60.0
            while self._is_process_alive() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.2)
            if self._is_process_alive():
                self.kill()
        await self._relay.shutdown()

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

    # =========================================
    #            Internal Helpers
    # =========================================

    def _is_process_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

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
                            loop.call_soon_threadsafe(self._relay.enqueue, cleaned)
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
            reason = (
                None
                if stop_requested or returncode == 0
                else f'Process exited unexpectedly (code {returncode}).'
            )
            loop.call_soon_threadsafe(self._finish_relay, reason)

    def _finish_relay(self, reason: str | None) -> None:
        self._relay.finish(reason=reason)
