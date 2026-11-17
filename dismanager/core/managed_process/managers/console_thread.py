from __future__ import annotations

import asyncio
import contextlib
import io
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING

import aiohttp
import discord

from ....discord.utils import get_or_create_thread
from ...bootstrap.i18n import _

if TYPE_CHECKING:
    from ..process import ManagedProcess

_RELAY_QUEUE_MAXSIZE = 1000
_RELAY_MESSAGE_LIMIT = 1990


class ConsoleThreadManager:
    """Manages a process's Discord console thread, log relay, direct messages, and log uploads."""

    _queue       : asyncio.Queue[str | None]
    _task        : asyncio.Task[None] | None
    _thread      : discord.Thread | None
    _stop_reason : str | None

    def __init__(self, process: ManagedProcess) -> None:
        self._process      = process
        self._client       = process.client
        self._queue        = asyncio.Queue(maxsize=_RELAY_QUEUE_MAXSIZE)
        self._omitted_logs = 0
        self._task         = None
        self._thread       = None
        self._stop_reason  = None
        self._finished     = False
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self._ensure_thread())

    # --- Internal Behaviour ---

    async def _ensure_thread(self) -> discord.Thread | None:
        panel = self._client._panel_manager.channel
        if panel is None:
            return None
        self._thread = await get_or_create_thread(panel, f'Console {self._process.name}')
        return self._thread

    async def _run(self, queue: asyncio.Queue[str | None]) -> None:
        thread = await self._ensure_thread()
        if thread is None:
            return

        with contextlib.suppress(aiohttp.ClientError, discord.HTTPException):
            await thread.send('```\n[Initializing Process...]\n```')

        pending_chunks: deque[str] = deque()
        saw_sentinel = False

        while not saw_sentinel or pending_chunks or self._omitted_logs > 0:
            try:
                if not pending_chunks and not saw_sentinel:
                    item = await queue.get()
                    if item is None:
                        saw_sentinel = True
                    else:
                        self._flush_omission_notice(pending_chunks)
                        self._append_sanitized_log(pending_chunks, item)
                        if not self._finished:
                            await asyncio.sleep(0.25)

                saw_sentinel = self._drain_ready_items(queue, pending_chunks, saw_sentinel=saw_sentinel)
                self._flush_omission_notice(pending_chunks)

                batch = self._take_relay_batch(pending_chunks)
                if batch:
                    await thread.send(f'```md\n{batch}```')

            except (aiohttp.ClientError, discord.HTTPException):
                await asyncio.sleep(1.0)
                with contextlib.suppress(Exception):
                    refetched = await self._ensure_thread()
                    if refetched is not None:
                        thread = refetched
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._client.report_error(f'ConsoleThreadManager:{self._process.name}')
                await asyncio.sleep(1.0)

        with contextlib.suppress(aiohttp.ClientError, discord.HTTPException):
            if self._stop_reason:
                await thread.send(f'```md\n{self._stop_reason[:_RELAY_MESSAGE_LIMIT]}\n```')
            await thread.send('```\n[Process Stopped]\n```')

    def _drain_ready_items(
        self,
        queue: asyncio.Queue[str | None],
        pending_chunks: deque[str],
        *,
        saw_sentinel: bool,
    ) -> bool:
        while not saw_sentinel and len(pending_chunks) < 100:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is None:
                saw_sentinel = True
                break
            self._flush_omission_notice(pending_chunks)
            self._append_sanitized_log(pending_chunks, item)
        return saw_sentinel

    def _flush_omission_notice(self, pending_chunks: deque[str]) -> None:
        if self._omitted_logs == 0:
            return
        omitted = self._omitted_logs
        self._omitted_logs = 0
        stamp = datetime.now().strftime('%H:%M:%S')
        pending_chunks.append(
            f'[DisManager] [{stamp}] [Relay/WARN]: Skipped {omitted} log lines to keep up with Discord rate limits.'
        )

    def _take_relay_batch(self, pending_chunks: deque[str]) -> str:
        batch: list[str] = []
        batch_size = 0

        while pending_chunks and batch_size < _RELAY_MESSAGE_LIMIT:
            log = pending_chunks.popleft()
            separator_size = 1 if batch else 0
            available = _RELAY_MESSAGE_LIMIT - batch_size - separator_size
            if available <= 0:
                pending_chunks.appendleft(log)
                break

            batch.append(log[:available])
            batch_size += separator_size + min(len(log), available)
            if len(log) > available:
                pending_chunks.appendleft(log[available:])
                break

        return '\n'.join(batch)

    def _append_sanitized_log(self, pending_chunks: deque[str], log: str) -> None:
        sanitized = log.replace('_', '⎽').replace('*', ' ').replace('`', '’').strip()
        if sanitized:
            pending_chunks.append(sanitized)

    # --- Internal API ---

    @property
    def thread(self) -> discord.Thread | None:
        """Return the resolved Discord console thread, if available."""
        return self._thread

    @property
    def is_active(self) -> bool:
        """Return ``True`` while the background relay task is running."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background relay task if it is not already running."""
        if self.is_active and not self._finished:
            return
        self._queue = asyncio.Queue(maxsize=_RELAY_QUEUE_MAXSIZE)
        self._omitted_logs = 0
        self._stop_reason = None
        self._finished = False
        queue = self._queue
        self._task = asyncio.create_task(self._run(queue), name=f'console-relay-{self._process.name}')

    def enqueue(self, line: str) -> None:
        """Push a log line into the bounded relay queue, skipping blacklisted lines."""
        if self._finished:
            return
        if any(term in line for term in self._process._config.blacklist):
            return

        try:
            self._queue.put_nowait(line)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                dropped = self._queue.get_nowait()
                if dropped is None:
                    return
                self._omitted_logs += 1
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(line)

    def finish(self, *, reason: str | None = None) -> None:
        """Signal the relay to drain remaining queued lines and stop."""
        if self._finished:
            return
        self._finished = True
        self._stop_reason = reason
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self._omitted_logs += 1
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(None)

    async def shutdown(self) -> None:
        """Stop the relay task cleanly."""
        self.finish()
        if self._task is not None and not self._task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def send_message(self, message: str) -> discord.Message | None:
        """Send a message directly to the process's Discord console thread."""
        thread = await self._ensure_thread()
        if thread is None:
            return None
        return await thread.send(message)

    async def send_log_file(self, data: bytes) -> discord.Message | None:
        """Send the process's recent 8 MB log buffer as a ``.log`` attachment."""
        thread = await self._ensure_thread()
        if thread is None:
            return None
        if not data:
            return await thread.send(_('The log file is currently empty.'))
        file = discord.File(io.BytesIO(data), filename=f'{self._process.name}.log')
        return await thread.send(file=file)
