## Context

Today `cobble/schedule.py`'s `Scheduler` owns one `maintenance_time` (`HH:MM`) and runs backup-then-update-check as a single nightly window, so the server is stopped at most once (see proposal.md - Why). `cobble/update/records.py`'s `UpdateStateStore` and `cobble/backup/service.py`'s `_last: BackupOutcome` each retain only the most recent outcome. `cobble/settings.py`'s `Settings` is `pydantic-settings`, resolved once at process start from env/TOML, and read through a process-wide `@lru_cache get_settings()` singleton — there is no write path.

This design covers the backend changes needed for: two independent, still-coordinating schedules; two durable append-only history logs; and a persisted, live-editable settings overlay. The UI is a straightforward consumer of the resulting APIs and is not detailed further here beyond the tab structure already agreed with the operator.

## Goals / Non-Goals

**Goals:**
- Backup and update-check schedules are independently configurable (time + daily/weekly/monthly + day selector) but still coordinate into one stop/start sequence when both fall due together.
- Every successful backup and every successful update is durably logged, independent of backup-file pruning.
- Backup retention, schedule enablement, and the two schedules are editable from the running process and persist across restarts, without requiring a TOML edit or a restart to take effect.
- The mandatory pre-update backup stays unconditional; it is not modeled as a setting.

**Non-Goals:**
- No change to the pre-update backup's behavior, its role in rollback, or its retention treatment (it is pruned by the same `backup_retention` pool as before).
- No general-purpose settings framework for every `Settings` field — only the fields named in the proposal (`backup_retention`, `backup_enabled`, and the two schedules) move to the new overlay. Everything else in `Settings` stays boot-time-only.
- No change to how a restore or a manual/on-demand backup or update works.
- No retroactive backfill of history: history starts recording from the first run after this change ships; nothing is synthesized for past updates/backups.

## Decisions

### 1. Two `ScheduleConfig`s replace one `maintenance_time`

Each of backup and update-check gets its own config: `{enabled, time (HH:MM), frequency (daily|weekly|monthly), day (weekday 0-6 for weekly, day-of-month 1-31 for monthly, ignored for daily)}`. `Scheduler` computes `next_run()` independently for each, using the existing "skip, don't catch up" rule per schedule (a schedule that was due while cobble was down waits for its next occurrence rather than firing late). A day-of-month value beyond the days in a given month (e.g. 31 in a 30-day month, or in February) clamps to that month's last day, so a fixed "31" setting still fires monthly instead of silently skipping months — this is called out explicitly since it was an open question during exploration.

**Alternative considered:** keep one shared schedule and add a per-operation multiplier (e.g. "run update check every Nth backup window"). Rejected — the operator explicitly asked for independent schedules, and a multiplier is a worse mental model than two plain schedules.

### 2. Coordination via a shared wake loop, not a shared trigger

The scheduler still runs a single asyncio loop, but it wakes at `min(backup.next_run(), update.next_run())` instead of one trigger. On each wake it re-evaluates both schedules independently: whichever are due now (within the existing jitter grace) run in one ordered sequence — update check/apply first is being flipped to backup-first to match the existing `server-backups` spec's documented order ("performed as a single ordered sequence with the backup first") — under **one** maintenance scope, so the server is stopped at most once for that wake. A schedule due on its own (the other not due) still runs through the same `_run_window`-style path, alone.

**Alternative considered:** two independent asyncio tasks/locks, one per schedule, with a mutex only to prevent literal concurrent execution. Rejected — that allows two consecutive stop/start cycles on a coinciding day (explicitly ruled out by the operator), and doesn't guarantee ordering when both happen to be due at once.

### 3. History stores follow the existing `UpdateStateStore` pattern

`backup/records.py` (`BackupHistoryStore`) and `update/history.py` (`UpdateHistoryStore`) are each a single JSON file under `state_dir`, written with the same read-modify-write-via-tmp-file approach already used by `UpdateStateStore._save()`. Each is an append-only list of small records:

- Backup history record: `{at, reason (manual|scheduled|pre-update), bedrock_version, size_bytes, archive, still_held (bool)}`. `still_held` is computed at read time by checking whether `archive` is still present in `BackupStore`, not stored statically, so a backup pruned after the record was written correctly reads back as no-longer-held without a second write.
- Version history record: `{at, from_version, to_version, trigger (manual|scheduled)}`.

Appended only on a successful outcome — a captured-and-verified backup (`BackupOutcome.ok`), or an update `UpdateResult.status == "success"`. Failures are not appended; they remain visible through the existing `last_result`/`FailedUpdateAlert` and `unhealthy` surfaces, which this change does not touch.

**Alternative considered:** a single combined "maintenance events" log for both backups and updates. Rejected — the two tabs the operator asked for map to two distinct read models with different fields (version pairs vs. archive/size); combining them would mean every consumer filters by event type anyway.

### 4. Settings overlay: a persisted layer above `Settings`, applied live

A new `MaintenanceSettingsStore` (JSON file, same pattern as above) holds only the fields moving to live editing: `backup_retention`, `backup_enabled`, `backup_schedule`, `update_schedule`. On read, the effective value for each of these fields is the overlay's value if present, else the `Settings`-resolved (env/TOML/default) value — so an untouched install behaves exactly as today. A `MaintenanceSettingsService` wraps this store and is what `Scheduler` and `BackupService` (for `backup_retention`) consult from now on, instead of reading `self._settings.backup_retention` etc. directly. Writing a setting updates the store, then calls back into `Scheduler` to recompute its next wake — no process restart, no cache invalidation needed elsewhere because nothing else cached these values.

`update_enabled` (whether the nightly window includes an update check at all) is **not** moved to this overlay in this change — the proposal did not ask for it, and the two new per-schedule `enabled` flags already give an operator a way to effectively disable update-checking (an update schedule with `enabled: false`). `maintenance_time`, `backup_enabled`, and `update_enabled` remain in `Settings` as the *fallback* values an overlay defers to when unset, so an operator who never opens the Settings tab keeps their existing TOML-configured behavior unchanged; they are not read directly by `Scheduler`/`BackupService` once this change lands.

**Alternative considered:** make the whole `Settings` object mutable and reloadable from a single merged file. Rejected as larger than needed — most fields (paths, timeouts, networking) have no live-edit requirement and changing them without a restart would be actively wrong (e.g. rebinding the HTTP port). Scoping the overlay to exactly the fields the operator asked to control keeps the blast radius small.

## Risks / Trade-offs

- **[Risk]** Two independently-firing schedules add real scheduling complexity (day clamping, jitter-grace coordination window, wake-time recomputation on a live settings edit) compared to today's single trigger. → Mitigation: the coordination logic is confined to `Scheduler`; `BackupService`/`UpdateService` are unaffected and keep their existing, already-tested `capture`/`apply` entry points.
- **[Risk]** History stores are unbounded JSON files that grow forever (unlike the pruned backup directory or the single-record `updates.json`). → Mitigation: out of scope to cap for this change (the operator didn't ask for history retention), but flagged here since a multi-year daily-backup install will eventually have a few thousand small records — trivial for JSON at that scale, revisit only if it becomes a real problem.
- **[Risk]** Existing `COBBLE_MAINTENANCE_TIME`/`COBBLE_BACKUP_ENABLED`/`COBBLE_UPDATE_ENABLED` env/TOML deployments get a changed schedule shape (one time -> two schedules) on upgrade. → Mitigation: see Migration Plan — the old single time seeds both new schedules' `time` on first run when no overlay file exists yet, so behavior is unchanged until the operator actively edits something in the new Settings tab.

## Migration Plan

- On first run after upgrade (no `MaintenanceSettingsStore` file yet on disk), both the backup schedule and the update schedule are seeded with `frequency: daily`, `time: <existing maintenance_time>`, `enabled: <existing backup_enabled / update_enabled respectively>` — reproducing today's combined-window behavior exactly (daily, same time, backup-first) until an operator changes something.
- No data migration needed for history — logs start empty and grow forward from first run.
- Rollback: reverting to a prior cobble version ignores the new overlay/history files (they live alongside, not replacing, `updates.json`); no destructive migration to undo.

## Open Questions

- None — the scheduling-coordination and settings-scope questions raised during exploration are resolved above (day clamping, backup-first ordering, `update_enabled` staying out of the overlay).
