"""The enforcement tracker: state by observation only (task 2.3)."""

from __future__ import annotations

from cobble.access.enforcement import Enforcement, EnforcementTracker
from cobble.events.model import AllowlistDisabled, AllowlistEnabled
from cobble.supervisor.state import RunState


def test_starts_unknown_and_never_guesses() -> None:
    t = EnforcementTracker()
    assert t.state is Enforcement.UNKNOWN
    assert t.observed is False


def test_follows_each_observed_transition() -> None:
    t = EnforcementTracker()
    t.on_event(AllowlistEnabled(raw="Turned on the allowlist"))
    assert t.state is Enforcement.ON
    assert t.observed is True
    t.on_event(AllowlistDisabled(raw="Turned off the allowlist"))
    assert t.state is Enforcement.OFF


def test_a_stop_forgets_a_stale_observation() -> None:
    t = EnforcementTracker()
    t.on_event(AllowlistEnabled(raw="Turned on the allowlist"))
    t.on_state_change(RunState.RUNNING, RunState.STOPPED)
    assert t.state is Enforcement.UNKNOWN


def test_note_records_a_transition_cobble_caused() -> None:
    t = EnforcementTracker()
    t.note(True)
    assert t.state is Enforcement.ON
