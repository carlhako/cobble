"""Live allowlist-enforcement state, learned only by observation (design.md D5).

BDS announces a change to allowlist enforcement (``Turned on the allowlist`` /
``Turned off the allowlist``) but offers **no command to read the current
state** — ``allowlist list`` returns members, never whether enforcement is on.
So the only honest source of the live value is the stream of transitions the
server prints, already flowing through the M1 parser.

The tracker starts :data:`Enforcement.UNKNOWN` and never guesses. When the server
is not running the previous process's observation is stale, so a stop resets it
to ``UNKNOWN``; the next server-ready re-asserts the saved value (task 2.4).
"""

from __future__ import annotations

import enum

from cobble.events.model import Event, EventType
from cobble.logging import get_logger
from cobble.supervisor.state import RunState

log = get_logger("access.enforcement")

_RESET_STATES = {
    RunState.STOPPED,
    RunState.CRASHED,
    RunState.FAILED,
    RunState.RECOVERY_ABANDONED,
}


class Enforcement(enum.StrEnum):
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


class EnforcementTracker:
    """Follows the allowlist-enforcement transitions the running server prints."""

    def __init__(self) -> None:
        self._state = Enforcement.UNKNOWN

    @property
    def state(self) -> Enforcement:
        return self._state

    @property
    def observed(self) -> bool:
        return self._state is not Enforcement.UNKNOWN

    # -- ingestion ------------------------------------------------
    def on_event(self, event: Event) -> None:
        """Bus callback. Fast and non-raising."""
        if event.type is EventType.ALLOWLIST_ENABLED:
            self._set(Enforcement.ON, event.raw)
        elif event.type is EventType.ALLOWLIST_DISABLED:
            self._set(Enforcement.OFF, event.raw)

    def on_state_change(self, _frm: RunState, to: RunState) -> None:
        """Supervisor run-state callback: a stopped server's last observation is
        stale, so forget it rather than report a guess."""
        if to in _RESET_STATES and self._state is not Enforcement.UNKNOWN:
            log.info("server left running state (%s); enforcement state back to unknown", to)
            self._state = Enforcement.UNKNOWN

    def note(self, on: bool) -> None:
        """Record a transition cobble itself just caused, so the state is correct
        without waiting for the announcement to round-trip through the parser."""
        self._set(Enforcement.ON if on else Enforcement.OFF, "(applied by cobble)")

    def _set(self, state: Enforcement, source: str) -> None:
        if state != self._state:
            log.info("allowlist enforcement observed %s: %s", state, source)
        self._state = state
