## Why

Operators can currently see only the *last* update result and whatever backups still happen to be sitting in the backup destination — older backups vanish from view the moment retention prunes them, and there is no record at all of when past updates landed. There is also no way to change backup retention, backup cadence, or update-check cadence without editing the TOML config file on the host and restarting cobble. Operators want to see this history in the web UI and configure the schedules from there.

## What Changes

- Add a durable **backup history** log: every successful backup capture (scheduled, manual, or pre-update) is appended as a permanent record, independent of whether the archive file itself is later pruned from disk.
- Add a durable **version history** log: every successful update is appended as a permanent record (from-version, to-version, when, trigger). Failed/rolled-back attempts are not logged here — they already surface through the existing failed-update alert.
- Add a new **maintenance settings** capability: operator-editable, persisted settings for backup retention, whether scheduled backups are enabled, and independent backup/update-check schedules (time of day plus daily/weekly/monthly frequency, with a day-of-week or day-of-month selector for the latter two). Changes take effect on the running process without a restart.
- **BREAKING (behavior)**: decouple the nightly backup and update-check schedules. Today they are one combined trigger that guarantees the server is stopped at most once. Going forward each has its own configurable schedule; when the two are due at (or near) the same time they are still coordinated into a single stop/start sequence, but they are no longer forced onto one daily trigger.
- Add three tabs to the Updates & Backups screen, under the existing version panel: **Backup history**, **Version history**, **Settings**. The existing live backup list/restore UI is unchanged; backup history is a separate, append-only view.
- The mandatory pre-update backup (the rollback safety net) remains unconditional — it is not exposed as a toggle, only documented as always-on in the new Settings tab.

## Capabilities

### New Capabilities
- `backup-history`: durable, append-only record of every successful backup capture, readable independently of which archives are still held on disk.
- `version-history`: durable, append-only record of every successful update, readable as a historical log.
- `maintenance-settings`: operator-editable, persisted configuration for backup retention and for the independent backup and update-check schedules; applied to the running process without a restart.

### Modified Capabilities
- `server-backups`: the recurring-backup requirement changes from a schedule shared with updates to an independently configurable schedule (time + daily/weekly/monthly frequency) that still coordinates with the update schedule to avoid a second stop/start when both are due together.
- `server-updates`: the recurring-check requirement changes from a schedule shared with backups to an independently configurable schedule (time + daily/weekly/monthly frequency), coordinated with the backup schedule the same way.

## Impact

- Backend: `cobble/backup/service.py`, new `cobble/backup/records.py` (history store); `cobble/update/service.py`, new `cobble/update/history.py`-style store distinct from the existing single-result `UpdateStateStore`; `cobble/schedule.py` reworked into two independent schedules with coordination; `cobble/settings.py` gains a writable, persisted overlay and a settings service; `cobble/status/tracker.py` reports per-schedule next-run times; new API endpoints under `cobble/api/` for reading history and reading/writing maintenance settings.
- Frontend: `web/src/sections/UpdatesBackups.tsx` restructured with a tabbed panel under the version box; `web/src/api/client.ts` gains history and settings types/calls.
- Config: `backup_enabled`/`update_enabled`/`maintenance_time` in `Settings` are superseded by the new per-schedule settings; existing TOML/env values need a migration or compatibility note since the schedule shape changes shape (single time -> time + frequency + day, per schedule).
