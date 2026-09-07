"""Task 3.2: the run-state model with guarded transitions."""

from __future__ import annotations

import pytest

from cobble.supervisor.state import RunState, StateMachine, TransitionError


def test_legal_path_start_run_stop() -> None:
    sm = StateMachine()
    assert sm.state is RunState.STOPPED
    sm.transition(RunState.STARTING)
    sm.transition(RunState.RUNNING)
    sm.transition(RunState.STOPPING)
    sm.transition(RunState.STOPPED)


def test_illegal_transition_raises() -> None:
    sm = StateMachine()
    with pytest.raises(TransitionError):
        sm.transition(RunState.RUNNING)  # stopped -> running is not allowed


def test_compare_and_transition_is_atomic_guard() -> None:
    sm = StateMachine()
    # First caller wins.
    assert sm.compare_and_transition(RunState.STOPPED, RunState.STARTING) is not None
    # Second caller sees a non-stopped state and is refused.
    assert sm.compare_and_transition(RunState.STOPPED, RunState.STARTING) is None


def test_listeners_receive_transitions() -> None:
    sm = StateMachine()
    seen: list[tuple[RunState, RunState]] = []
    sm.subscribe(lambda frm, to: seen.append((frm, to)))
    sm.transition(RunState.STARTING)
    sm.transition(RunState.RUNNING)
    assert seen == [
        (RunState.STOPPED, RunState.STARTING),
        (RunState.STARTING, RunState.RUNNING),
    ]
