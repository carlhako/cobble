"""Recording observed sessions (tasks 2.1-2.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cobble.events.bus import EventBus
from cobble.events.model import PlayerConnected, PlayerDisconnected, PlayerSpawned, RawOutput
from cobble.players.recorder import SessionRecorder
from cobble.players.storage import END_OBSERVED, END_RECONSTRUCTED, open_store


class FakeClock:
    def __init__(self) -> None:
        self.t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


def _store(tmp_path: Path):
    return open_store(tmp_path / "cobble.db")


# -- 2.1 subscriber writes rows -------------------------------------
def test_connect_spawn_disconnect_produce_a_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    clock = FakeClock()
    bus = EventBus()
    bus.subscribe(SessionRecorder(store, clock=clock).on_event)

    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    clock.advance(6)
    bus.publish(PlayerSpawned(raw="", xuid="x1", gamertag="Alex"))
    clock.advance(3600)
    bus.publish(PlayerDisconnected(raw="", xuid="x1", gamertag="Alex"))

    rows = store.sessions_for("x1", now=clock())
    assert len(rows) == 1
    s = rows[0]
    assert s.spawned_at is not None
    assert s.end_reason == END_OBSERVED
    assert s.duration_seconds == 3606.0
    store.close()


def test_unrelated_events_are_ignored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    bus = EventBus()
    bus.subscribe(SessionRecorder(store, clock=FakeClock()).on_event)
    bus.publish(RawOutput(raw="some chatter"))
    assert store.roster(now=datetime.now(UTC)) == []
    store.close()


# -- 2.2 times come from the injected clock ------------------------
def test_recorded_time_comes_from_the_clock_not_the_line(tmp_path: Path) -> None:
    store = _store(tmp_path)
    clock = FakeClock()
    rec = SessionRecorder(store, clock=clock)
    # A log line whose text mentions a quite different time must not be used.
    rec.on_event(
        PlayerConnected(raw="[1999-01-01 00:00:00:000 INFO] Player connected: Alex", xuid="x1")
    )
    connected_at = store.sessions_for("x1", now=clock())[0].connected_at
    assert connected_at == clock().isoformat()
    store.close()


# -- 2.3 write failures are contained -----------------------------
def test_write_failure_does_not_raise(tmp_path: Path) -> None:
    class Boom:
        def has_open_session(self, xuid: str) -> bool:
            return False

        def open_session(self, *a, **k):
            raise RuntimeError("disk gone")

    rec = SessionRecorder(Boom(), clock=FakeClock())  # type: ignore[arg-type]
    # Must return normally — the bus callback contract, and D7.
    rec.on_event(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))


def test_bus_delivers_to_other_consumers_when_recorder_fails(tmp_path: Path) -> None:
    class Boom:
        def has_open_session(self, xuid: str) -> bool:
            return False

        def open_session(self, *a, **k):
            raise RuntimeError("disk gone")

    seen: list[str] = []
    bus = EventBus()
    bus.subscribe(SessionRecorder(Boom(), clock=FakeClock()).on_event)  # type: ignore[arg-type]
    bus.subscribe(lambda e: seen.append(e.type))
    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    assert seen == ["player_connected"]


# -- 2.4 reconnect starts a new session, no merging ---------------
def test_reconnect_shortly_after_leaving_is_two_sessions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    clock = FakeClock()
    bus = EventBus()
    bus.subscribe(SessionRecorder(store, clock=clock).on_event)

    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    clock.advance(100)
    bus.publish(PlayerDisconnected(raw="", xuid="x1", gamertag="Alex"))
    clock.advance(6.24)  # the disconnect->reconnect gap from the captured data
    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))

    rows = store.sessions_for("x1", now=clock())
    assert len(rows) == 2
    assert rows[0].connected_at != rows[1].connected_at
    assert rows[1].end_reason == END_OBSERVED  # the earlier, closed one
    assert rows[0].in_progress is True  # the reconnect
    store.close()


def test_connect_while_a_session_is_still_open_closes_the_stale_one(tmp_path: Path) -> None:
    store = _store(tmp_path)
    clock = FakeClock()
    rec = SessionRecorder(store, clock=clock)

    rec.on_event(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    clock.advance(30)
    rec.on_event(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))  # no disconnect seen

    rows = store.sessions_for("x1", now=clock())
    assert len(rows) == 2
    stale = rows[1]
    assert stale.end_reason == END_RECONSTRUCTED
    assert rows[0].in_progress is True
    store.close()
