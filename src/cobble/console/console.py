"""The console: live fan-out of server output to many clients and serialized
relay of operator commands to the server's stdin (server-console spec).

* On connect a client is given the retained history, then live output, with no
  gap and no duplication (sequence numbers bridge the two).
* Output fan-out is per-subscriber and bounded: a slow or vanished client cannot
  stall the server or other clients.
* Command submission is serialized and echoed to every client; it is refused
  when the server is not running.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from cobble.console.buffer import ConsoleBuffer, ConsoleLine
from cobble.logging import get_logger
from cobble.supervisor.supervisor import NotRunningError, Supervisor

log = get_logger("console")

_SUBSCRIBER_QUEUE_MAX = 4096


class _Subscriber:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[ConsoleLine] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAX)
        self.dropped = 0

    def offer(self, line: ConsoleLine) -> None:
        try:
            self.queue.put_nowait(line)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
                self.dropped += 1
            self.queue.put_nowait(line)


class Console:
    def __init__(self, supervisor: Supervisor) -> None:
        self._sup = supervisor
        self._buffer: ConsoleBuffer = supervisor.console
        self._subscribers: set[_Subscriber] = set()
        self._command_lock = asyncio.Lock()
        self._buffer.add_listener(self._on_line)

    @property
    def buffer(self) -> ConsoleBuffer:
        return self._buffer

    def _on_line(self, line: ConsoleLine) -> None:
        for sub in list(self._subscribers):
            sub.offer(line)

    async def stream(self) -> AsyncIterator[ConsoleLine]:
        """Retained history followed by live output. Never raises if the server
        is stopped: the client simply waits and receives output once it starts.
        """
        sub = _Subscriber()
        self._subscribers.add(sub)
        try:
            history = self._buffer.snapshot()
            last_seq = history[-1].seq if history else 0
            for line in history:
                yield line
            while True:
                line = await sub.queue.get()
                if line.seq <= last_seq:
                    continue  # already delivered as history
                last_seq = line.seq
                yield line
        finally:
            self._subscribers.discard(sub)

    async def submit_command(self, command: str) -> None:
        command = command.rstrip("\n")
        async with self._command_lock:
            # Reject before echoing so a rejected command never appears in the
            # stream (server-console spec: "the command is not queued").
            if not self._sup_is_running():
                raise NotRunningError("the server is not running")
            self._buffer.add_command(command)  # echoed to all clients
            await self._sup.send_command(command)

    def _sup_is_running(self) -> bool:
        from cobble.supervisor.state import RunState

        return self._sup.state is RunState.RUNNING

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
