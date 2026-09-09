"""A session ended by a kick is attributed to it (tasks 4.3, 4.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cobble.events.bus import EventBus
from cobble.events.model import PlayerConnected, PlayerDisconnected
from cobble.players.kick import KickIntentRegistry
from cobble.players.recorder import SessionRecorder
from cobble.players.storage import END_KICKED, END_OBSERVED, open_store


class FakeClock:
    def __init__(self) -> None:
        self.t = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class MonoClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def _wire(tmp_path: Path, registry: KickIntentRegistry):
    store = open_store(tmp_path / "cobble.db")
    clock = FakeClock()
    bus = EventBus()
    bus.subscribe(SessionRecorder(store, clock=clock, kick_intents=registry).on_event)
    return store, clock, bus


# -- 4.3 kicked departure records the kick; unregistered is directly observed --
def test_a_kicked_departure_records_the_kick_reason(tmp_path: Path) -> None:
    registry = KickIntentRegistry(clock=MonoClock())
    store, clock, bus = _wire(tmp_path, registry)

    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    clock.advance(120)
    registry.register("x1", "griefing", ttl=5.0)  # access service did this before the command
    bus.publish(PlayerDisconnected(raw="", xuid="x1", gamertag="Alex"))

    (s,) = store.sessions_for("x1", now=clock())
    assert s.end_reason == END_KICKED
    assert s.approximate is False  # a kicked session's playtime is exact (4.3)
    assert s.duration_seconds == 120.0
    store.close()


def test_an_unregistered_departure_records_as_directly_observed(tmp_path: Path) -> None:
    registry = KickIntentRegistry(clock=MonoClock())
    store, clock, bus = _wire(tmp_path, registry)

    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    clock.advance(60)
    bus.publish(PlayerDisconnected(raw="", xuid="x1", gamertag="Alex"))

    (s,) = store.sessions_for("x1", now=clock())
    assert s.end_reason == END_OBSERVED
    store.close()


# -- 4.4 an intent no departure satisfies expires ------------
def test_a_departure_after_the_bound_is_not_attributed_to_the_kick(tmp_path: Path) -> None:
    mono = MonoClock()
    registry = KickIntentRegistry(clock=mono)
    store, clock, bus = _wire(tmp_path, registry)

    bus.publish(PlayerConnected(raw="", xuid="x1", gamertag="Alex"))
    registry.register("x1", "afk", ttl=5.0)
    mono.advance(30)  # the kick produced no departure; the player leaves later, voluntarily
    clock.advance(1800)
    bus.publish(PlayerDisconnected(raw="", xuid="x1", gamertag="Alex"))

    (s,) = store.sessions_for("x1", now=clock())
    assert s.end_reason == END_OBSERVED  # not misattributed
    store.close()
