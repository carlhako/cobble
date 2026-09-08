"""Derived, pushed status view (server-status spec).

The tracker owns no lifecycle logic. It observes:

* supervisor run-state transitions — for run state, uptime bracketing, and the
  online-player reset when the server stops;
* the typed event stream — for readiness (uptime start) and player connect/
  disconnect (the online set).

Any change produces a new :class:`StatusSnapshot` pushed to subscribers, so the
interface never polls (server-status spec: "Status changes are pushed").
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from cobble.acquisition.version import is_newer
from cobble.events.model import (
    Event,
    EventType,
    PlayerConnected,
    PlayerDisconnected,
    PlayerSpawned,
)
from cobble.logging import get_logger
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import Supervisor

log = get_logger("status")

_RESET_STATES = {
    RunState.STOPPED,
    RunState.CRASHED,
    RunState.FAILED,
    RunState.RECOVERY_ABANDONED,
}


@dataclass(frozen=True)
class OnlinePlayer:
    xuid: str
    gamertag: str


@dataclass(frozen=True)
class ShutdownView:
    clean: bool
    at: str


@dataclass(frozen=True)
class CrashView:
    exit_code: int | None
    at: str
    recovery: str  # restarting | running | abandoned | crashed


@dataclass(frozen=True)
class MaintenanceView:
    operation: str  # updating | restoring | backing_up
    step: str | None


@dataclass(frozen=True)
class VersionView:
    installed: str | None
    available: str | None  # None => no successful check yet (unknown)
    up_to_date: bool | None  # None => unknown


@dataclass(frozen=True)
class UpdateView:
    last_check_at: str | None
    last_result: dict | None
    next_scheduled_at: str | None
    skipping: str | None  # the available version being skipped, or None
    terminal: bool


@dataclass(frozen=True)
class BackupView:
    last_at: str | None
    last_ok: bool | None
    next_scheduled_at: str | None
    unhealthy: str | None  # reason backups are failing, or None
    count: int


@dataclass(frozen=True)
class ConfigView:
    pending: bool
    pending_count: int


@dataclass(frozen=True)
class StatusSnapshot:
    run_state: RunState
    version: str | None
    uptime_seconds: float | None
    online_players: tuple[OnlinePlayer, ...]
    players_incomplete: bool
    last_shutdown: ShutdownView | None
    bootstrap: str = "skipped"
    bootstrap_detail: str = ""
    last_crash: CrashView | None = None
    maintenance: MaintenanceView | None = None
    version_info: VersionView | None = None
    update: UpdateView | None = None
    backup: BackupView | None = None
    config: ConfigView | None = None
    gamerules: dict | None = None

    def to_dict(self) -> dict:
        return {
            "run_state": self.run_state.value,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "online_players": [
                {"xuid": p.xuid, "gamertag": p.gamertag} for p in self.online_players
            ],
            "players_incomplete": self.players_incomplete,
            "last_shutdown": (
                None
                if self.last_shutdown is None
                else {"clean": self.last_shutdown.clean, "at": self.last_shutdown.at}
            ),
            "bootstrap": self.bootstrap,
            "bootstrap_detail": self.bootstrap_detail,
            "last_crash": (
                None
                if self.last_crash is None
                else {
                    "exit_code": self.last_crash.exit_code,
                    "at": self.last_crash.at,
                    "recovery": self.last_crash.recovery,
                }
            ),
            "maintenance": (
                None
                if self.maintenance is None
                else {"operation": self.maintenance.operation, "step": self.maintenance.step}
            ),
            "version_info": (
                None
                if self.version_info is None
                else {
                    "installed": self.version_info.installed,
                    "available": self.version_info.available,
                    "up_to_date": self.version_info.up_to_date,
                }
            ),
            "update": (
                None
                if self.update is None
                else {
                    "last_check_at": self.update.last_check_at,
                    "last_result": self.update.last_result,
                    "next_scheduled_at": self.update.next_scheduled_at,
                    "skipping": self.update.skipping,
                    "terminal": self.update.terminal,
                }
            ),
            "backup": (
                None
                if self.backup is None
                else {
                    "last_at": self.backup.last_at,
                    "last_ok": self.backup.last_ok,
                    "next_scheduled_at": self.backup.next_scheduled_at,
                    "unhealthy": self.backup.unhealthy,
                    "count": self.backup.count,
                }
            ),
            "config": (
                None
                if self.config is None
                else {
                    "pending": self.config.pending,
                    "pending_count": self.config.pending_count,
                }
            ),
            "gamerules": self.gamerules,
        }


@dataclass(eq=False)
class _Sub:
    queue: asyncio.Queue[StatusSnapshot] = field(default_factory=lambda: asyncio.Queue(maxsize=64))


class StatusTracker:
    def __init__(
        self,
        supervisor: Supervisor,
        *,
        clock=time.monotonic,
        bootstrap=None,
        update=None,
        backup=None,
        scheduler=None,
        config=None,
        gamerules=None,
    ) -> None:
        self._sup = supervisor
        self._clock = clock
        self._bootstrap = bootstrap  # object with .state / .detail, or None
        self._update = update  # UpdateService or None
        self._backup = backup  # BackupService or None
        self._scheduler = scheduler  # Scheduler or None
        self._config = config  # ConfigService or None
        self._gamerules = gamerules  # GameruleManager or None
        self._online: dict[str, str] = {}  # xuid -> gamertag
        self._incomplete = False
        self._subs: set[_Sub] = set()

        supervisor.subscribe_state(self._on_state_change)
        # Maintenance step changes are pushed to connected clients without
        # polling (server-status spec, task 8.3).
        supervisor.subscribe_maintenance(lambda _op, _step: self._emit())

    def notify(self) -> None:
        """Force a status push (used when a field the tracker doesn't observe,
        e.g. bootstrap progress, has changed)."""
        self._emit()

    # -- event ingestion --------------------------------------
    def on_event(self, event: Event) -> None:
        """Callback for the event bus. Fast and non-raising."""
        if event.type == EventType.PLAYER_CONNECTED and isinstance(event, PlayerConnected):
            self._online[event.xuid] = event.gamertag
            self._emit()
        elif event.type == EventType.PLAYER_SPAWNED and isinstance(event, PlayerSpawned):
            if event.xuid not in self._online:
                # Saw a spawn without the preceding connect — history is partial.
                self._incomplete = True
                self._online[event.xuid] = event.gamertag
                self._emit()
        elif event.type == EventType.PLAYER_DISCONNECTED and isinstance(event, PlayerDisconnected):
            if event.xuid not in self._online:
                self._incomplete = True
            self._online.pop(event.xuid, None)
            self._emit()

    def _on_state_change(self, _frm: RunState, to: RunState) -> None:
        if to in _RESET_STATES:
            self._online.clear()
            # A fresh start from here observes the whole session again.
            if to == RunState.STOPPED:
                self._incomplete = False
        self._emit()

    def mark_observation_incomplete(self) -> None:
        """Called by the runtime when cobble cannot account for the full
        connection history of the running server (e.g. it restored a session it
        did not watch start)."""
        self._incomplete = True
        self._emit()

    # -- snapshot / push ------------------------------------
    def snapshot(self) -> StatusSnapshot:
        rec = self._sup.last_shutdown
        crash = self._sup.last_crash
        state = self._sup.state
        if crash is None:
            recovery = "none"
        elif state == RunState.RUNNING:
            recovery = "running"
        elif state == RunState.RECOVERY_ABANDONED:
            recovery = "abandoned"
        elif state in (RunState.CRASHED, RunState.STARTING):
            recovery = "restarting"
        else:
            recovery = "stopped"
        return StatusSnapshot(
            run_state=self._sup.state,
            version=self._sup.installed_version(),
            uptime_seconds=self._sup.uptime_seconds,
            online_players=tuple(
                OnlinePlayer(xuid=x, gamertag=g) for x, g in sorted(self._online.items())
            ),
            players_incomplete=self._incomplete and self._sup.state == RunState.RUNNING,
            last_shutdown=None if rec is None else ShutdownView(clean=rec.clean, at=rec.at),
            bootstrap=getattr(self._bootstrap, "state", "skipped"),
            bootstrap_detail=getattr(self._bootstrap, "detail", ""),
            last_crash=(
                None
                if crash is None
                else CrashView(exit_code=crash.exit_code, at=crash.at, recovery=recovery)
            ),
            maintenance=(
                None
                if self._sup.maintenance is None
                else MaintenanceView(
                    operation=self._sup.maintenance, step=self._sup.maintenance_step
                )
            ),
            version_info=self._version_view(),
            update=self._update_view(),
            backup=self._backup_view(),
            config=self._config_view(),
            gamerules=self._gamerules_block(),
        )

    def _gamerules_block(self) -> dict | None:
        if self._gamerules is None:
            return None
        try:
            return self._gamerules.status_block()
        except Exception:
            log.exception("gamerule status block failed; reporting none")
            return None

    def _config_view(self) -> ConfigView | None:
        if self._config is None:
            return None
        try:
            changes = self._config.pending()
        except Exception:
            log.exception("config pending comparison failed; reporting none")
            changes = []
        return ConfigView(pending=bool(changes), pending_count=len(changes))

    def _next_scheduled(self) -> str | None:
        if self._scheduler is None:
            return None
        nxt = self._scheduler.next_run()
        return nxt.isoformat() if nxt is not None else None

    def _version_view(self) -> VersionView | None:
        installed = self._sup.installed_version()
        available = self._update.available_version if self._update is not None else None
        if self._update is None:
            return VersionView(installed=installed, available=None, up_to_date=None)
        if available is None:
            up_to_date: bool | None = None  # no successful check yet (task 9.1)
        elif installed is None:
            up_to_date = None
        else:
            up_to_date = available == installed or not is_newer(available, installed)
        return VersionView(installed=installed, available=available, up_to_date=up_to_date)

    def _update_view(self) -> UpdateView | None:
        if self._update is None:
            return None
        rec = self._update.last_result
        available = self._update.available_version
        return UpdateView(
            last_check_at=self._update.last_check_at,
            last_result=(
                None
                if rec is None
                else {
                    "status": rec.status,
                    "at": rec.at,
                    "detail": rec.detail,
                    "from_version": rec.from_version,
                    "to_version": rec.to_version,
                    "step": rec.step,
                }
            ),
            next_scheduled_at=self._next_scheduled(),
            skipping=(available if available and self._update.is_skipping(available) else None),
            terminal=self._update.terminal,
        )

    def _backup_view(self) -> BackupView | None:
        if self._backup is None:
            return None
        outcome = self._backup.last_outcome
        try:
            count = len(self._backup.store.list(verify=False))
        except Exception:
            count = 0
        return BackupView(
            last_at=outcome.at if outcome is not None else None,
            last_ok=outcome.ok if outcome is not None else None,
            next_scheduled_at=self._next_scheduled(),
            unhealthy=self._backup.health,
            count=count,
        )

    def _emit(self) -> None:
        snap = self.snapshot()
        for sub in list(self._subs):
            try:
                sub.queue.put_nowait(snap)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
                sub.queue.put_nowait(snap)

    async def stream(self) -> AsyncIterator[StatusSnapshot]:
        """Current snapshot immediately, then one on every change."""
        sub = _Sub()
        self._subs.add(sub)
        try:
            yield self.snapshot()
            while True:
                yield await sub.queue.get()
        finally:
            self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
