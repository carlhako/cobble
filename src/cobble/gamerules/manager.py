"""The gamerule world manager: per-world records, readiness/pre-stop sampling,
drift reconciliation, and the stopped-server view (server-gamerules spec).

Wired in :mod:`cobble.runtime` to the event bus (server readiness) and the
supervisor's pre-stop hook, the same way the player recorder is. Every storage
failure is logged and swallowed: a gamerule problem never disturbs the server or
the readiness path.

Readiness reconciliation (design.md D5, D6, D8) compares the live set against the
per-world record and takes one of four branches:

* **baseline** — live matches the record (or a first-sight world with no
  preferred defaults): the record is (re)written, nothing is reported.
* **adoption** — the live set diverges and cobble did not cause it: the live
  values become the record and an unacknowledged report names them. The server
  is left as the operator set it.
* **repair** — the divergence is the first readiness after a restore: the
  recorded values are re-applied to the server and a repair report names them.
* **defaults** — a world with no record and preferred defaults set: the defaults
  are applied, the resulting set becomes the record, and a report names them.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from cobble.events.model import Event, EventType
from cobble.gamerules.catalogue import RuleType, lookup
from cobble.gamerules.parser import GameruleSet, set_from_values
from cobble.gamerules.service import (
    GameruleService,
    GameruleUnavailableError,
    coerce_submit_value,
)
from cobble.gamerules.storage import (
    REPORT_ADOPTION,
    REPORT_DEFAULTS,
    REPORT_REPAIR,
    GameruleStorageError,
    GameruleStore,
    Report,
)
from cobble.logging import get_logger
from cobble.supervisor.state import RunState
from cobble.supervisor.supervisor import MaintenanceInProgressError, Supervisor

log = get_logger("gamerules.manager")

_DEFAULT_LEVEL_NAME = "Bedrock level"

WorldNameFn = Callable[[], str]

RuleValue = bool | int | str


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Liveness(StrEnum):
    LIVE = "live"  # read from the running server just now
    RECORDED = "recorded"  # from the per-world record; server not running
    UNREAD = "unread"  # no record and the server is not running


class Classification(StrEnum):
    BASELINE = "baseline"
    ADOPTION = "adoption"
    REPAIR = "repair"
    DEFAULTS = "defaults"
    UNAVAILABLE = "unavailable"  # live set could not be read
    STORAGE_ERROR = "storage_error"  # the record could not be read/written


@dataclass(frozen=True)
class ReconcileOutcome:
    level_name: str
    classification: Classification
    rules: dict[str, RuleValue] = field(default_factory=dict)  # rules the branch acted on


@dataclass(frozen=True)
class WriteResult:
    queued: bool  # True: server stopped, stored for the next start; False: applied now
    level_name: str
    rules: GameruleSet | None  # the re-read set when applied; None when queued
    pending: dict[str, RuleValue] = field(default_factory=dict)


def _typed_value(rule, submit_value: str) -> RuleValue:
    """The catalogue-typed value for a validated ``submit_value`` string."""
    if rule is None:
        return submit_value
    if rule.type is RuleType.BOOL:
        return submit_value == "true"
    if rule.type is RuleType.INT:
        return int(submit_value)
    return submit_value


@dataclass(frozen=True)
class GameruleView:
    level_name: str
    liveness: Liveness
    sampled_at: str | None  # when a RECORDED set was taken; None otherwise
    rules: GameruleSet  # empty when UNREAD
    report: Report | None  # an unacknowledged adoption / repair / defaults report


def _diff(old: dict[str, RuleValue], new: dict[str, RuleValue]) -> dict[str, RuleValue]:
    """Rules whose value in ``new`` differs from ``old`` (added or changed),
    mapped to their ``new`` value."""
    return {name: value for name, value in new.items() if old.get(name) != value}


class GameruleManager:
    def __init__(
        self,
        service: GameruleService,
        store: GameruleStore,
        supervisor: Supervisor,
        world_name: WorldNameFn,
        *,
        on_report: Callable[[], None] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._service = service
        self._store = store
        self._sup = supervisor
        self._world_name = world_name
        self._on_report = on_report
        self._clock = clock
        self._tasks: set[asyncio.Task] = set()

        supervisor.subscribe_pre_stop(self._on_pre_stop)

    # -- world identity ---------------------------------------
    def active_world(self) -> str:
        """The world whose rules are in play: the name the running server was
        started with, or the configured ``level-name`` when it is stopped
        (it cannot change while the server runs — design.md Risks)."""
        snap = self._sup.config_snapshot
        if snap is not None:
            return (snap.get("level-name") or "").strip() or _DEFAULT_LEVEL_NAME
        try:
            return self._world_name() or _DEFAULT_LEVEL_NAME
        except Exception:
            log.exception("could not determine the active world; using the default name")
            return _DEFAULT_LEVEL_NAME

    # -- event bus / supervisor hooks ------------------------
    def on_event(self, event: Event) -> None:
        """Bus callback (fast, non-raising). A readiness event triggers
        reconciliation on a task so the bus is never blocked."""
        if event.type is EventType.SERVER_READY:
            self._spawn(self.on_ready(), "cobble-gamerule-ready")

    def _on_pre_stop(self, when: datetime) -> None:
        # Best-effort, fire-and-forget: the server is about to go away and the
        # start sample makes the record correct again (design.md D4).
        if self._sup.state is not RunState.RUNNING:
            return
        self._spawn(self._safe_sample("pre_stop", when), "cobble-gamerule-prestop-sample")

    def _spawn(self, coro, name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- readiness reconciliation (task 4.1) -----------------
    async def on_ready(self) -> ReconcileOutcome:
        try:
            # The readiness event fires from the stdout pump *before* the
            # supervisor transitions to RUNNING, and console queries are refused
            # until it does. Wait for that transition (bounded) so the first
            # reconcile can actually read the live set.
            if self._sup.state is not RunState.RUNNING:
                waiter = getattr(self._sup, "wait_for_state", None)
                if waiter is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(waiter(RunState.RUNNING), timeout=30)
            return await self.reconcile()
        except Exception:
            log.exception("gamerule readiness reconciliation failed; server unaffected")
            return ReconcileOutcome(self.active_world(), Classification.STORAGE_ERROR)

    async def reconcile(self) -> ReconcileOutcome:
        world = self.active_world()
        try:
            live = await self._service.read_live()
        except GameruleUnavailableError as exc:
            log.info("gamerule reconcile skipped for %r: %s", world, exc)
            return ReconcileOutcome(world, Classification.UNAVAILABLE)

        now = self._clock()
        try:
            record = self._store.read_record(world)
            restored = self._store.take_restore_marker(world)
            pending = self._store.read_pending(world)

            if record is None:
                outcome = await self._first_sight(world, live, now)
            else:
                # Divergence attributed to an in-game change: differs from the
                # record and is not one of the operator's own queued writes.
                diverged = {
                    name: value
                    for name, value in _diff(record.values, live.value_map()).items()
                    if name not in pending
                }
                if restored:
                    outcome = await self._repair(world, live, record.values, diverged, now)
                elif diverged:
                    outcome = await self._adopt(world, live, diverged, now)
                else:
                    self._store.write_record(world, live.value_map(), now)
                    outcome = ReconcileOutcome(world, Classification.BASELINE)

            # Apply the operator's queued stopped-server writes on top and make
            # the resulting set the record (task 5.5).
            if pending:
                await self._safe_apply(pending, live)
                self._store.clear_pending(world)
                fresh = await self._reread_or(live)
                self._store.write_record(world, fresh.value_map(), now)
                log.info(
                    "gamerule pending writes applied for %r: %s",
                    world,
                    ", ".join(sorted(pending)),
                )
            return outcome
        except GameruleStorageError:
            log.exception("gamerule reconcile: storage unavailable for %r", world)
            return ReconcileOutcome(world, Classification.STORAGE_ERROR)

    async def _first_sight(
        self, world: str, live: GameruleSet, now: datetime
    ) -> ReconcileOutcome:
        defaults = self._store.read_defaults()
        if not defaults:
            # A world seen for the first time with no preferred defaults: record
            # what is already there, change nothing (task 4.7).
            self._store.write_record(world, live.value_map(), now)
            return ReconcileOutcome(world, Classification.BASELINE)

        applied = await self._safe_apply(defaults, live)
        fresh = await self._reread_or(live)
        self._store.write_record(world, fresh.value_map(), now)
        self._record_report(world, REPORT_DEFAULTS, applied, now)
        return ReconcileOutcome(world, Classification.DEFAULTS, applied)

    async def _adopt(
        self, world: str, live: GameruleSet, diverged: dict[str, RuleValue], now: datetime
    ) -> ReconcileOutcome:
        # Store the live values; the server is left exactly as the operator set
        # it — nothing is written back (task 4.2).
        self._store.write_record(world, live.value_map(), now)
        self._record_report(world, REPORT_ADOPTION, diverged, now)
        return ReconcileOutcome(world, Classification.ADOPTION, diverged)

    async def _repair(
        self,
        world: str,
        live: GameruleSet,
        recorded: dict[str, RuleValue],
        diverged: dict[str, RuleValue],
        now: datetime,
    ) -> ReconcileOutcome:
        # The marker has already been consumed by ``take_restore_marker`` above,
        # so it is cleared whether or not a divergence is found (design.md D6).
        if not diverged:
            return ReconcileOutcome(world, Classification.BASELINE)

        put_back = {name: recorded[name] for name in diverged if name in recorded}
        await self._safe_apply(put_back, live)
        # The record already holds the correct values; keep them, refresh nothing
        # about their content.
        self._record_report(world, REPORT_REPAIR, put_back, now)
        return ReconcileOutcome(world, Classification.REPAIR, put_back)

    async def _safe_apply(
        self, values: dict[str, RuleValue], live: GameruleSet
    ) -> dict[str, RuleValue]:
        try:
            await self._service.apply_many(values)
        except GameruleUnavailableError:
            log.warning("gamerule reconcile: server went away while applying values")
        return values

    async def _reread_or(self, fallback: GameruleSet) -> GameruleSet:
        try:
            return await self._service.read_live()
        except GameruleUnavailableError:
            return fallback

    def _record_report(
        self, world: str, kind: str, rules: dict[str, RuleValue], now: datetime
    ) -> None:
        self._store.write_report(Report(world, kind, now.isoformat(), rules))
        log.info("gamerule %s for %r: %s", kind, world, ", ".join(sorted(rules)) or "(none)")
        self._notify_report()

    # -- restore marker (task 4.3) --------------------------
    def mark_restored(self, level_name: str) -> None:
        """Called by the restore path after a completed restore, naming the
        world it replaced. The next readiness repairs rather than adopts."""
        try:
            self._store.set_restore_marker(level_name, self._clock())
            log.info("gamerule restore marker set for %r", level_name)
        except GameruleStorageError:
            log.exception("setting the gamerule restore marker for %r failed", level_name)

    # -- operator writes (tasks 4.8, 5.5) -----------------
    async def write_rule(self, name: str, value: object) -> WriteResult:
        """Apply an operator's gamerule change.

        Refused with the maintenance error while an update, backup, or restore is
        in progress (task 4.8). When the server is running the change is applied
        immediately and the re-read set returned. When it is stopped the value is
        pre-validated and queued as the intended value for the active world, to
        be applied at the next start (task 5.5) — no command is issued.
        """
        if self._sup.maintenance is not None:
            raise MaintenanceInProgressError(
                f"a {self._sup.maintenance} operation is in progress"
            )
        world = self.active_world()
        if self._sup.state is RunState.RUNNING:
            rules = await self._service.write(name, value)
            return WriteResult(queued=False, level_name=world, rules=rules)

        # Stopped: validate against the catalogue (raises GameruleRefusedError),
        # then queue it.
        rule = lookup(name)
        canonical, submit_value = coerce_submit_value(rule, name.strip(), value)
        coerced = _typed_value(rule, submit_value)
        self._store.set_pending(world, canonical, coerced)
        log.info("gamerule %s=%r queued for %r (server stopped)", canonical, coerced, world)
        return WriteResult(
            queued=True, level_name=world, rules=None, pending={canonical: coerced}
        )

    def pending_writes(self, level_name: str | None = None) -> dict[str, RuleValue]:
        try:
            return self._store.read_pending(level_name or self.active_world())
        except GameruleStorageError:
            log.exception("reading queued gamerule writes failed")
            return {}

    # -- the status block (task 5.6) ----------------------
    def status_block(self) -> dict:
        """A cheap, console-free summary for the status payload: the active
        world, whether its set is live / recorded / unread, when it was last
        read, and any unacknowledged report."""
        world = self.active_world()
        running = self._sup.state is RunState.RUNNING
        try:
            rec = self._store.read_record(world)
            report = self._store.read_report(world)
        except GameruleStorageError:
            log.exception("gamerule status block: storage unavailable")
            rec, report = None, None
        if running:
            liveness = Liveness.LIVE
        elif rec is not None:
            liveness = Liveness.RECORDED
        else:
            liveness = Liveness.UNREAD
        return {
            "active_world": world,
            "liveness": liveness.value,
            "last_read_at": rec.sampled_at if rec is not None else None,
            "report": report.to_dict() if report is not None else None,
        }

    # -- sampling (tasks 3.3, 3.4) -------------------------
    async def sample_and_store(self, *, reason: str, at: datetime | None = None) -> bool:
        world = self.active_world()
        try:
            live = await self._service.read_live()
        except GameruleUnavailableError as exc:
            log.info("gamerule sample (%s) skipped for %r: %s", reason, world, exc)
            return False
        try:
            self._store.write_record(world, live.value_map(), at or self._clock())
        except GameruleStorageError:
            log.exception("storing the gamerule record for %r failed (%s)", world, reason)
            return False
        log.info("gamerule record for %r updated (%s)", world, reason)
        return True

    async def _safe_sample(self, reason: str, when: datetime) -> None:
        with contextlib.suppress(Exception):
            await self.sample_and_store(reason=reason, at=when)

    # -- the current view (task 3.5) ----------------------
    async def current_view(self) -> GameruleView:
        world = self.active_world()
        report = self._safe_read_report(world)

        if self._sup.state is RunState.RUNNING:
            try:
                live = await self._service.read_live()
                return GameruleView(
                    level_name=world,
                    liveness=Liveness.LIVE,
                    sampled_at=self._clock().isoformat(),
                    rules=live,
                    report=report,
                )
            except GameruleUnavailableError:
                log.info("live gamerule read failed for %r; serving the record", world)

        rec = self._safe_read_record(world)
        if rec is None:
            return GameruleView(world, Liveness.UNREAD, None, GameruleSet(rules=()), report)
        return GameruleView(
            level_name=world,
            liveness=Liveness.RECORDED,
            sampled_at=rec.sampled_at,
            rules=set_from_values(rec.values),
            report=report,
        )

    # -- preferred defaults (used by the API, section 5) --
    def read_defaults(self) -> dict[str, RuleValue]:
        try:
            return self._store.read_defaults()
        except GameruleStorageError:
            log.exception("reading preferred gamerule defaults failed")
            return {}

    def set_default(self, name: str, value: object) -> dict[str, RuleValue]:
        """Validate ``value`` against the catalogue and store it as the preferred
        default for ``name``. Raises :class:`GameruleRefusedError` on a bad
        value (task 5.3)."""
        rule = lookup(name)
        canonical, submit_value = coerce_submit_value(rule, name.strip(), value)
        self._store.set_default(canonical, _typed_value(rule, submit_value))
        return self.read_defaults()

    def clear_default(self, name: str) -> dict[str, RuleValue]:
        rule = lookup(name)
        self._store.clear_default(rule.name if rule is not None else name.strip())
        return self.read_defaults()

    def acknowledge_report(self, level_name: str) -> None:
        """Clear the unacknowledged report for ``level_name`` without touching
        any recorded value (task 5.4)."""
        self._store.clear_report(level_name)
        self._notify_report()

    # -- storage guards (task 3.6) -----------------------
    def _safe_read_record(self, world: str):
        try:
            return self._store.read_record(world)
        except GameruleStorageError:
            log.exception("reading the gamerule record for %r failed", world)
            return None

    def _safe_read_report(self, world: str) -> Report | None:
        try:
            return self._store.read_report(world)
        except GameruleStorageError:
            log.exception("reading the gamerule report for %r failed", world)
            return None

    def _notify_report(self) -> None:
        if self._on_report is not None:
            try:
                self._on_report()
            except Exception:
                log.exception("gamerule report notification failed")

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._store.close()
