"""The run-state model (server-status spec: "Run state is exposed").

States:

* ``stopped``   — no process; last stop was intentional (or never started).
* ``starting``  — process spawned, awaiting the readiness signal.
* ``running``   — readiness observed.
* ``stopping``  — a stop was requested; awaiting exit.
* ``crashed``   — process exited without a stop being requested.
* ``failed``    — a start attempt did not reach readiness within the timeout.
* ``recovery_abandoned`` — automatic crash-restart gave up after repeated crashes;
  a manual start is still possible.

Transitions are guarded: an illegal transition raises rather than silently
corrupting state.
"""

from __future__ import annotations

import enum
import threading
from collections.abc import Callable


class RunState(enum.StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"
    FAILED = "failed"
    RECOVERY_ABANDONED = "recovery_abandoned"


# Allowed transitions. Keys are the current state; values the states reachable
# from it in one step.
_ALLOWED: dict[RunState, set[RunState]] = {
    RunState.STOPPED: {RunState.STARTING},
    RunState.STARTING: {RunState.RUNNING, RunState.FAILED, RunState.STOPPING, RunState.CRASHED},
    RunState.RUNNING: {RunState.STOPPING, RunState.CRASHED},
    RunState.STOPPING: {RunState.STOPPED, RunState.CRASHED},
    RunState.CRASHED: {RunState.STARTING, RunState.RECOVERY_ABANDONED, RunState.STOPPED},
    RunState.FAILED: {RunState.STARTING, RunState.STOPPED},
    RunState.RECOVERY_ABANDONED: {RunState.STARTING, RunState.STOPPED},
}

_RUNNINGISH = {RunState.STARTING, RunState.RUNNING, RunState.STOPPING}


class TransitionError(RuntimeError):
    """An illegal run-state transition was attempted."""

    def __init__(self, frm: RunState, to: RunState) -> None:
        super().__init__(f"illegal run-state transition {frm.value} -> {to.value}")
        self.frm = frm
        self.to = to


class StateMachine:
    """Thread-safe holder of the current run state with guarded transitions.

    A lock plus explicit transition rules make concurrent start requests safe:
    the first moves ``stopped -> starting``; a second, seeing a non-``stopped``
    state, is rejected by the caller before any process is spawned.
    """

    def __init__(self, initial: RunState = RunState.STOPPED) -> None:
        self._state = initial
        self._lock = threading.Lock()
        self._listeners: list[Callable[[RunState, RunState], None]] = []

    @property
    def state(self) -> RunState:
        with self._lock:
            return self._state

    def is_active(self) -> bool:
        """True when a process exists or is expected to (starting/running/stopping)."""
        return self.state in _RUNNINGISH

    def subscribe(self, listener: Callable[[RunState, RunState], None]) -> None:
        self._listeners.append(listener)

    def can(self, to: RunState) -> bool:
        return to in _ALLOWED.get(self.state, set())

    def transition(self, to: RunState, *, force: bool = False) -> tuple[RunState, RunState]:
        with self._lock:
            frm = self._state
            if to == frm:
                return frm, to
            if not force and to not in _ALLOWED.get(frm, set()):
                raise TransitionError(frm, to)
            self._state = to
        for listener in list(self._listeners):
            listener(frm, to)
        return frm, to

    def compare_and_transition(
        self, expected: RunState, to: RunState
    ) -> tuple[RunState, RunState] | None:
        """Atomically transition only if the current state is ``expected``.

        Returns the ``(from, to)`` pair on success, or ``None`` if the current
        state was not ``expected`` (the caller then reports the conflict).
        """
        with self._lock:
            if self._state != expected:
                return None
            if to not in _ALLOWED.get(self._state, set()):
                raise TransitionError(self._state, to)
            frm = self._state
            self._state = to
        for listener in list(self._listeners):
            listener(frm, to)
        return frm, to
