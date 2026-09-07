"""Bounded in-memory buffer of recent console output (server-console spec:
"Recent console history is available on connect").

* Memory is bounded: the buffer keeps at most ``maxlen`` entries, discarding the
  oldest first.
* History survives a Bedrock restart while cobble keeps running, and the restart
  is distinguishable in the stream via a ``marker`` entry.
* Each entry has a monotonic sequence number so a reconnecting client and a live
  subscriber can be given a consistent, de-duplicated view.
"""

from __future__ import annotations

import enum
import itertools
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass


class LineKind(enum.StrEnum):
    OUTPUT = "output"  # a line from the server
    COMMAND = "command"  # a command an operator submitted (echoed)
    MARKER = "marker"  # a lifecycle boundary, e.g. server restarted


@dataclass(frozen=True)
class ConsoleLine:
    seq: int
    kind: LineKind
    text: str


class ConsoleBuffer:
    def __init__(self, maxlen: int) -> None:
        self._lines: deque[ConsoleLine] = deque(maxlen=maxlen)
        self._counter = itertools.count(1)
        self._listeners: list[Callable[[ConsoleLine], None]] = []

    def add_listener(self, listener: Callable[[ConsoleLine], None]) -> Callable[[], None]:
        """Register a callback fired on every appended line (output, command, or
        marker). Returns an unsubscribe callable. A listener that raises is
        isolated by the caller of ``_append``'s notify loop.
        """
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    @property
    def maxlen(self) -> int:
        assert self._lines.maxlen is not None
        return self._lines.maxlen

    def __len__(self) -> int:
        return len(self._lines)

    def _append(self, kind: LineKind, text: str) -> ConsoleLine:
        line = ConsoleLine(seq=next(self._counter), kind=kind, text=text)
        self._lines.append(line)
        for listener in list(self._listeners):
            try:
                listener(line)
            except Exception:  # a bad listener must not corrupt the buffer
                from cobble.logging import get_logger

                get_logger("console.buffer").exception("console listener raised")
        return line

    def add_output(self, text: str) -> ConsoleLine:
        return self._append(LineKind.OUTPUT, text)

    def add_command(self, text: str) -> ConsoleLine:
        return self._append(LineKind.COMMAND, text)

    def add_marker(self, text: str) -> ConsoleLine:
        return self._append(LineKind.MARKER, text)

    def snapshot(self, after_seq: int = 0) -> list[ConsoleLine]:
        """Retained lines with ``seq > after_seq``, oldest first."""
        return [line for line in self._lines if line.seq > after_seq]

    def last_seq(self) -> int:
        return self._lines[-1].seq if self._lines else 0

    def extend_output(self, texts: Iterable[str]) -> None:
        for text in texts:
            self.add_output(text)
