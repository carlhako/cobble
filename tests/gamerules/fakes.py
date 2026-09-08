"""Shared test doubles for the gamerule manager and API tests."""

from __future__ import annotations

from datetime import UTC, datetime

from cobble.gamerules.catalogue import lookup
from cobble.gamerules.parser import GameruleSet, set_from_values
from cobble.gamerules.service import (
    GameruleRefusedError,
    GameruleUnavailableError,
    coerce_submit_value,
)
from cobble.supervisor.state import RunState


class FakeSupervisor:
    def __init__(self, *, running: bool = True, level_name: str = "world-a") -> None:
        self.state = RunState.RUNNING if running else RunState.STOPPED
        self.maintenance: str | None = None
        self._level = level_name
        self._pre_stop: list = []

    @property
    def config_snapshot(self) -> dict | None:
        return {"level-name": self._level} if self.state is RunState.RUNNING else None

    def set_running(self, running: bool) -> None:
        self.state = RunState.RUNNING if running else RunState.STOPPED

    async def wait_for_state(self, *targets: RunState) -> RunState:
        return self.state

    def subscribe_pre_stop(self, fn) -> None:
        self._pre_stop.append(fn)

    def fire_pre_stop(self, when: datetime | None = None) -> None:
        when = when or datetime.now(UTC)
        for fn in list(self._pre_stop):
            fn(when)


class FakeGameruleService:
    """Stands in for :class:`cobble.gamerules.service.GameruleService`."""

    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values) if values else {}
        self.unavailable = False
        self.reads = 0
        self.writes: list[tuple[str, object]] = []
        self.refuse: dict[str, str] = {}  # rule -> reason

    async def read_live(self) -> GameruleSet:
        self.reads += 1
        if self.unavailable:
            raise GameruleUnavailableError("the server did not answer")
        return set_from_values(self.values)

    async def write(self, name: str, value: object) -> GameruleSet:
        if self.unavailable:
            raise GameruleUnavailableError("the server is not running")
        # Pre-validate against the catalogue exactly like the real service.
        canonical, submit_value = coerce_submit_value(lookup(name), name.strip(), value)
        if canonical in self.refuse:
            raise GameruleRefusedError(canonical, self.refuse[canonical])
        typed: object = value
        rule = lookup(canonical)
        if rule is not None and str(rule.type) == "bool":
            typed = submit_value == "true"
        elif rule is not None and str(rule.type) == "int":
            typed = int(submit_value)
        self.writes.append((canonical, typed))
        self.values[canonical] = typed
        return set_from_values(self.values)

    async def apply_many(self, values: dict) -> GameruleSet:
        if self.unavailable:
            raise GameruleUnavailableError("the server is not running")
        for name, value in values.items():
            if name in self.refuse:
                continue
            self.writes.append((name, value))
            self.values[name] = value
        return set_from_values(self.values)


class RaisingStore:
    """A store whose every method raises, to prove the manager swallows it."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __getattr__(self, _name):
        def _raise(*_a, **_k):
            raise self._exc

        return _raise
