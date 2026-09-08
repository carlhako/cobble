"""The console: live fan-out of server output to many clients and serialized
relay of operator commands to the server's stdin (server-console spec).

* On connect a client is given the retained history, then live output, with no
  gap and no duplication (sequence numbers bridge the two).
* Output fan-out is per-subscriber and bounded: a slow or vanished client cannot
  stall the server or other clients.
* Command submission is serialized and echoed to every client; it is refused
  when the server is not running.
* Cobble can also query the server on its own behalf via :meth:`Console.query`:
  the command is not echoed and the reply line is withheld from client fan-out
  (server-console spec: "Cobble can query the server without disturbing the
  console"). This path is not reachable from the API router.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable

from cobble.console.buffer import ConsoleBuffer, ConsoleLine, LineKind
from cobble.logging import get_logger
from cobble.supervisor.supervisor import NotRunningError, Supervisor

log = get_logger("console")

_SUBSCRIBER_QUEUE_MAX = 4096

# The default bound on an internal query: the server replies to a bulk `gamerule`
# read on the same line it is issued, so a few seconds is generous.
_DEFAULT_QUERY_TIMEOUT = 5.0

LineMatcher = Callable[[str], bool]


class InternalQueryError(RuntimeError):
    """An internal (cobble-originated) console query could not be completed —
    the server produced no reply matching the expected shape in time."""

    code = "internal_query_failed"


class _PendingQuery:
    __slots__ = ("future", "matcher")

    def __init__(self, matcher: LineMatcher, future: asyncio.Future[str]) -> None:
        self.matcher = matcher
        self.future = future


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
        # Outstanding cobble-originated queries and the sequence numbers of the
        # reply lines they consumed, so a reconnecting client never replays one
        # from history (server-console spec).
        self._pending_queries: list[_PendingQuery] = []
        self._suppressed_seqs: set[int] = set()
        self._buffer.add_listener(self._on_line)

    @property
    def buffer(self) -> ConsoleBuffer:
        return self._buffer

    def _on_line(self, line: ConsoleLine) -> None:
        if line.kind is LineKind.OUTPUT and self._pending_queries:
            for pending in list(self._pending_queries):
                if pending.future.done():
                    continue
                try:
                    matched = pending.matcher(line.text)
                except Exception:
                    log.exception("internal query matcher raised; passing the line through")
                    matched = False
                if matched:
                    pending.future.set_result(line.text)
                    self._discard_pending(pending)
                    self._suppressed_seqs.add(line.seq)
                    self._bound_suppressed()
                    # Logged so a false match (an unrelated line that fit the
                    # shape) is diagnosable (design.md Risks).
                    log.info("internal query consumed console line seq=%d: %s", line.seq, line.text)
                    return  # withheld from client fan-out
        for sub in list(self._subscribers):
            sub.offer(line)

    def _bound_suppressed(self) -> None:
        # Each successful query adds one seq; keep the set from growing without
        # bound over a long-lived process. Older lines have rolled out of the
        # buffer and can never be replayed as history.
        if len(self._suppressed_seqs) > 512:
            for seq in sorted(self._suppressed_seqs)[:-256]:
                self._suppressed_seqs.discard(seq)

    def _discard_pending(self, pending: _PendingQuery) -> None:
        with contextlib.suppress(ValueError):
            self._pending_queries.remove(pending)

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
                if line.seq in self._suppressed_seqs:
                    continue  # a cobble-originated query's reply
                yield line
            while True:
                line = await sub.queue.get()
                if line.seq <= last_seq:
                    continue  # already delivered as history
                last_seq = line.seq
                if line.seq in self._suppressed_seqs:
                    continue
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

    async def query(
        self,
        command: str,
        matcher: LineMatcher,
        *,
        reply_timeout: float = _DEFAULT_QUERY_TIMEOUT,
    ) -> str:
        """Send a command cobble originates on its own behalf and return the
        first server output line matching ``matcher``.

        The command is not echoed to console clients and the matched reply is
        withheld from them (server-console spec). Server output that does not
        match is delivered to clients as usual.

        Raises :class:`NotRunningError` if the server is not running (the query
        is not queued), and :class:`InternalQueryError` if no matching line
        arrives within ``timeout`` (the console and the server are left
        untouched).
        """
        command = command.rstrip("\n")
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        pending = _PendingQuery(matcher, fut)
        async with self._command_lock:
            if not self._sup_is_running():
                raise NotRunningError("the server is not running")
            # Register the matcher before the command is sent so the reply,
            # which can only arrive afterwards, cannot be missed.
            self._pending_queries.append(pending)
            try:
                await self._sup.send_command(command)  # not buffered: not echoed
            except Exception:
                self._discard_pending(pending)
                raise
        try:
            return await asyncio.wait_for(fut, reply_timeout)
        except TimeoutError as exc:
            raise InternalQueryError(
                f"the server produced no reply matching the expected shape "
                f"within {reply_timeout:g}s"
            ) from exc
        finally:
            self._discard_pending(pending)

    def _sup_is_running(self) -> bool:
        from cobble.supervisor.state import RunState

        return self._sup.state is RunState.RUNNING

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
