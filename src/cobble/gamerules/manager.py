"""The gamerule world manager: per-world records, drift reconciliation, and the
stopped-server view (server-gamerules spec).

Wired in :mod:`cobble.runtime` to the event bus (server readiness). Every storage
failure is logged and swallowed: a gamerule problem never disturbs the server or
the readiness path.

The record is written at readiness (below), after every write cobble makes while
the server runs, and on every live read that finds it out of date once that
run's readiness reconcile has finished. A live read that diverges from the
record is an adoption, exactly as at readiness; so is a divergence in any rule
other than the one written that a write's re-read turns up. Nothing is sampled
at stop: the record already holds the last set cobble read or wrote. One lock
serialises all of these so a read that lands mid-write cannot mistake cobble's
own write for an outside change (fix-gamerule-record-staleness design.md D1-D4).

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
    GameruleUnconfirmedError,
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
# How long a write while running waits for an in-flight readiness reconcile
# before going ahead anyway (fix-gamerule-record-staleness design.md D2).
_READINESS_WAIT = 10.0

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
        # Serialises every record-touching operation (design.md D1).
        self._lock = asyncio.Lock()
        # Set while no readiness reconcile is in flight; cleared on readiness.
        self._readiness_done = asyncio.Event()
        self._readiness_done.set()
        # Whether this run's readiness reconcile succeeded, so live reads may
        # update the record (design.md D2).
        self._run_reconciled = False

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
            # Synchronous, so it happens before the supervisor reaches RUNNING
            # and before any live read or write can touch the record.
            self._run_reconciled = False
            self._readiness_done.clear()
            self._spawn(self.on_ready(), "cobble-gamerule-ready")

    def _spawn(self, coro, name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # -- readiness reconciliation (task 4.1) -----------------
    async def on_ready(self) -> ReconcileOutcome:
        try:
            return await self._on_ready()
        finally:
            self._readiness_done.set()

    async def _on_ready(self) -> ReconcileOutcome:
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
        async with self._lock:
            outcome = await self._reconcile()
        if outcome.classification not in (
            Classification.UNAVAILABLE,
            Classification.STORAGE_ERROR,
        ):
            self._run_reconciled = True
        return outcome

    async def _reconcile(self) -> ReconcileOutcome:
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
                    outcome = self._adopt(world, live, diverged, now)
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

    def _adopt(
        self, world: str, live: GameruleSet, diverged: dict[str, RuleValue], now: datetime
    ) -> ReconcileOutcome:
        # Store the live values; the server is left exactly as the operator set
        # it — nothing is written back (task 4.2).
        self._store.write_record(world, live.value_map(), now)
        # An adoption the operator has not acknowledged yet is extended, not
        # replaced, so a rule it named is not dropped before it is seen.
        prior = self._store.read_report(world)
        reported = diverged
        if prior is not None and prior.kind == REPORT_ADOPTION:
            reported = {**prior.rules, **diverged}
        self._record_report(world, REPORT_ADOPTION, reported, now)
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
        try:
            fresh = await self._service.read_live()
        except GameruleUnavailableError:
            # The server went away mid-repair: keep the recorded values as the
            # record, since they are still the ones intended.
            pass
        else:
            # A value the server refused is still live as the restore left it.
            # Record what is in effect, so the first live read does not take it
            # for an in-game change, and report only what was put back.
            in_effect = fresh.value_map()
            self._store.write_record(world, in_effect, now)
            put_back = {n: v for n, v in put_back.items() if in_effect.get(n) == v}
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
        self._refuse_during_maintenance()
        if self._sup.state is RunState.RUNNING:
            # Let an in-flight readiness reconcile decide first, so this write
            # cannot pre-empt a repair or first-sight defaults (design.md D2).
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._readiness_done.wait(), _READINESS_WAIT)
        async with self._lock:
            # Checked again: maintenance may have begun, or the server stopped,
            # while this write waited for readiness or the lock.
            self._refuse_during_maintenance()
            world = self.active_world()
            if self._sup.state is RunState.RUNNING:
                rules = await self._write_running(world, name, value)
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

    def _refuse_during_maintenance(self) -> None:
        if self._sup.maintenance is not None:
            raise MaintenanceInProgressError(
                f"a {self._sup.maintenance} operation is in progress"
            )

    async def _write_running(self, world: str, name: str, value: object) -> GameruleSet:
        """Send the write and bring the record up to date with it. Caller holds
        the lock."""
        try:
            rules = await self._service.write(name, value)
        except GameruleUnconfirmedError as exc:
            # The server most likely took the value but the re-read was lost.
            # Record it anyway, so it is never reported as an outside change.
            self._record_written_value(world, exc.rule, exc.submit_value)
            raise
        if self._run_reconciled:
            # The written rule is cobble's own change; any other divergence the
            # re-read turns up was made in game and is adopted.
            rule = lookup(name)
            self._absorb_live(world, rules, exclude=rule.name if rule else name.strip())
        else:
            # Readiness has not decided yet (or could not): take the re-read as
            # the record, at worst a baseline taken early (design.md D2).
            self._safe_write_record(world, rules)
        return rules

    def _record_written_value(self, world: str, name: str, submit_value: str) -> None:
        try:
            record = self._store.read_record(world)
            if record is None:
                return
            values = {**record.values, name: _typed_value(lookup(name), submit_value)}
            self._store.write_record(world, values, self._clock())
        except GameruleStorageError:
            log.exception("storing an unconfirmed gamerule write for %r failed", world)

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

    # -- the current view (task 3.5) ----------------------
    async def current_view(self) -> GameruleView:
        world = self.active_world()

        if self._sup.state is RunState.RUNNING:
            try:
                if self._run_reconciled:
                    async with self._lock:
                        live = await self._service.read_live()
                        # Checked again: a new readiness may have arrived while
                        # this read waited for the lock.
                        if self._run_reconciled:
                            self._absorb_live(world, live)
                else:
                    # Before readiness has decided, the record is not touched,
                    # so there is nothing to wait for (design.md D2).
                    live = await self._service.read_live()
                # Read after reconciling so a report just made is included.
                report = self._safe_read_report(world)
                return GameruleView(
                    level_name=world,
                    liveness=Liveness.LIVE,
                    sampled_at=self._clock().isoformat(),
                    rules=live,
                    report=report,
                )
            except GameruleUnavailableError:
                log.info("live gamerule read failed for %r; serving the record", world)

        report = self._safe_read_report(world)
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

    def _absorb_live(self, world: str, live: GameruleSet, *, exclude: str | None = None) -> None:
        """Bring the record up to date with a live set read after readiness.
        A divergence in any rule but ``exclude`` (cobble's own write) is adopted.
        Repair and defaults are readiness-only decisions, so after readiness the
        only unexplained divergence is an outside change (design.md D3). A
        matching set leaves the record alone: rewriting it would only move
        ``last_read_at``, which makes the UI reload. Caller holds the lock."""
        values = live.value_map()
        try:
            record = self._store.read_record(world)
            if record is not None and record.values == values:
                return
            now = self._clock()
            diverged = (
                {n: v for n, v in _diff(record.values, values).items() if n != exclude}
                if record is not None
                else {}
            )
            if diverged:
                self._adopt(world, live, diverged, now)
            else:
                self._store.write_record(world, values, now)
        except GameruleStorageError:
            log.exception("updating the gamerule record from a live read failed for %r", world)

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
    def _safe_write_record(self, world: str, rules: GameruleSet) -> None:
        try:
            self._store.write_record(world, rules.value_map(), self._clock())
        except GameruleStorageError:
            log.exception("storing the gamerule record for %r failed", world)

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
