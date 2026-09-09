"""Shared test doubles for the access service / documents / store tests."""

from __future__ import annotations

from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import NotRunningError


class FakeConsole:
    """Records commands submitted through the echoed path; can pretend the server
    is not running."""

    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.submitted: list[str] = []
        self.queries: list[tuple[str, float]] = []

    async def submit_command(self, command: str) -> None:
        if not self.running:
            raise NotRunningError("the server is not running")
        self.submitted.append(command)

    async def query(self, command: str, matcher, *, reply_timeout: float = 5.0) -> str:
        self.queries.append((command, reply_timeout))
        if not self.running:
            raise NotRunningError("the server is not running")
        return command


class FakeSupervisor:
    def __init__(self, *, running: bool = True, level_name: str = "world-a") -> None:
        self.state = RunState.RUNNING if running else RunState.STOPPED
        self.maintenance: str | None = None
        self._level = level_name
        self._state_subs: list = []
        self._pre_stop: list = []

    @property
    def config_snapshot(self) -> dict | None:
        return {"level-name": self._level} if self.state is RunState.RUNNING else None

    def subscribe_state(self, fn) -> None:
        self._state_subs.append(fn)

    def subscribe_pre_stop(self, fn) -> None:
        self._pre_stop.append(fn)

    async def wait_for_state(self, *targets: RunState) -> RunState:
        return self.state

    def set_running(self, running: bool) -> None:
        frm = self.state
        self.state = RunState.RUNNING if running else RunState.STOPPED
        for fn in list(self._state_subs):
            fn(frm, self.state)
