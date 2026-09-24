## 1. Maintenance settings overlay

- [x] 1.1 Add `cobble/maintenance/settings_store.py` (or similar) with a `MaintenanceSettingsStore` persisting `{backup_retention, backup_enabled, backup_schedule, update_schedule}` as JSON under `state_dir`, following `UpdateStateStore`'s tmp-file-write pattern; unit test load/save round-trip and malformed-file fallback in `tests/maintenance/test_settings_store.py`.
- [x] 1.2 Define the `ScheduleConfig` shape (`enabled`, `time` HH:MM, `frequency` daily|weekly|monthly, `day`) with validation (weekly day 0-6, monthly day 1-31, HH:MM format) and unit-test invalid inputs are rejected.
- [x] 1.3 Add `MaintenanceSettingsService` that layers the store over `Settings` fallback values (`backup_retention`, `backup_enabled`, `maintenance_time` seed both schedules) so an untouched install is unaffected; unit test the fallback-vs-overlay precedence.
- [x] 1.4 On first run with no overlay file, seed both schedules from the existing `maintenance_time`/`backup_enabled`/`update_enabled` so upgraded installs keep today's daily/shared-time/backup-first behavior until an operator changes something; test this seeding explicitly.
- [x] 1.5 Wire `BackupService` to read `backup_retention` from `MaintenanceSettingsService` instead of `Settings` directly; existing retention tests in `tests/backup/test_service.py` continue to pass.

## 2. Scheduler decoupling

- [x] 2.1 Rework `cobble/schedule.py`'s `Scheduler` to hold two independent `ScheduleConfig` reads (backup, update) via `MaintenanceSettingsService`, each with its own `next_run()` using the existing skip-not-catch-up and jitter-grace rules; extend `parse_hhmm`/date-math helpers for weekly (day-of-week) and monthly (day-of-month, clamped to the month's last day) frequencies.
- [x] 2.2 Change the wake loop to sleep until `min(backup.next_run(), update.next_run())` and re-evaluate both schedules on each wake.
- [x] 2.3 When both schedules are due together (within jitter grace), run one coordinated window: backup first, then update check/apply, under a single maintenance scope so the server stops at most once; when only one is due, run it alone via the same underlying path.
- [x] 2.4 Add a method to recompute/reschedule the wake immediately when settings change (called from the new settings-write API path in task 4), so an edited schedule takes effect without a restart.
- [x] 2.5 Update/extend `tests/test_schedule.py`: independent daily/weekly/monthly next-run computation, day-of-month clamping (e.g. 31 in a 30-day month, Feb 29/30/31), coordinated same-day run stops the server once, non-coinciding runs behave independently, disabled-schedule behavior for each schedule separately.

## 3. Backup history

- [x] 3.1 Add `cobble/backup/records.py` (`BackupHistoryStore`) storing `{at, reason, bedrock_version, size_bytes, archive}` records as an append-only JSON list, same file-write pattern as `UpdateStateStore`.
- [x] 3.2 Append a record from `BackupService._archive_verify_prune` (and `capture_pre_migration`) on every successful, verified capture; no record on failure. Unit test in `tests/backup/test_service.py` that success appends and failure does not.
- [x] 3.3 Add a read method that lists history newest-first, computing `still_held` at read time against `BackupStore` rather than storing it; unit test a pruned archive reads back as not held while its record remains.
- [x] 3.4 Add `GET /api/backups/history` in `src/cobble/api/backups.py` returning the list (empty list, not error, when none exist); add/extend an API test in `tests/api/test_updates_backups.py`.

## 4. Version history

- [x] 4.1 Add `cobble/update/history.py` (`UpdateHistoryStore`) storing `{at, from_version, to_version, trigger}` records as an append-only JSON list.
- [x] 4.2 Append a record from `UpdateService._record` only when `status == "success"`; no record for `up_to_date`, `skipped`, `aborted`, `rolled_back`, or `terminal`. Unit test in `tests/update/test_update_service.py` covering each status appends or does not append as specified.
- [x] 4.3 Add a read method listing history newest-first.
- [x] 4.4 Add `GET /api/updates/history` in `src/cobble/api/updates.py` returning the list; add/extend an API test.

## 5. Settings API

- [x] 5.1 Add `GET /api/maintenance/settings` returning the effective `{backup_retention, backup_enabled, backup_schedule, update_schedule}` plus a fixed `pre_update_backup_always_on: true` marker for the UI's info-only note.
- [x] 5.2 Add `PUT /api/maintenance/settings` (or per-field endpoints, matching this codebase's existing config-write convention in `src/cobble/api/config.py`) validating and persisting changes, then triggering the scheduler reschedule from task 2.4; reject invalid schedule shapes (bad day-of-week/month, malformed time) with the same validation-error convention used in `server-config`'s write path.
- [x] 5.3 Add API tests: a valid write persists and survives a simulated restart (re-reading the store), an invalid write is rejected and leaves prior settings intact, a write while a maintenance operation is in progress behaves consistently with other config writes during maintenance (see `server-config`'s "Configuration writes are refused during maintenance" precedent — decide and test whether settings writes follow the same rule).

## 6. Status surfacing

- [x] 6.1 Update `cobble/status/tracker.py`'s `UpdateView`/`BackupView` (or add fields) so `next_scheduled_at` reflects each schedule's own `next_run()` independently instead of one shared value; update `to_dict()` and any snapshot tests in `tests/status/test_tracker.py`.
- [x] 6.2 Confirm existing status consumers (SSE stream, `tests/api/test_sse_live.py`) still pass with independently-valued next-run fields.

## 7. Frontend: tabs and data

- [x] 7.1 Add `BackupEntry`-like types and client calls in `web/src/api/client.ts` for backup history, version history, and maintenance settings (get/put).
- [x] 7.2 Restructure `web/src/sections/UpdatesBackups.tsx`: add a tabbed panel under `VersionPanel` with "Backup history", "Version history", "Settings" tabs; keep the existing live `BackupsPanel` (capture/restore/download) as-is, unaffected by the new tabs.
- [x] 7.3 Implement the Backup history tab: table of history records (captured time, version, size, trigger, held/pruned status), loaded via the new endpoint.
- [x] 7.4 Implement the Version history tab: table of history records (installed time, from-version, to-version, trigger).
- [x] 7.5 Implement the Settings tab: retention number input, scheduled-backups on/off, backup-before-upgrade shown as always-on informational text (no control), and two schedule editors (time + daily/weekly/monthly + conditional day-of-week/day-of-month picker) for backup and update-check respectively; wire to the settings API with validation errors surfaced inline.
- [x] 7.6 Add/extend `web/src/test/updates_backups.test.tsx` covering: tab switching, backup history rendering (including a pruned/not-held row), version history rendering, settings form read/write round-trip, and that the pre-update backup control is absent.

## 8. Docs and migration

- [x] 8.1 Update any operator-facing config documentation that describes `maintenance_time`/`backup_enabled`/`update_enabled` to note they are now first-run seed values for the live-editable schedules, superseded by the Settings tab/API once an operator saves a change there.
- [ ] 8.2 Manually verify on a live host (per existing live-verification setup) that: an upgrade with no prior overlay file preserves today's daily/shared-time behavior; editing a schedule in the UI changes `next_scheduled_at` without a restart; a coordinated same-day backup+update run stops the server exactly once.
