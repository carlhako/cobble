# Proposal

## Why

Scheduled maintenance runs at the operator's chosen time in whatever timezone the cobble process happens to have, and most LXC and container hosts are set to UTC. On cobble-3 a daily schedule set for 04:00 ran at 14:00 local time (04:00 UTC for an operator on UTC+10). The panel did not show the problem: the next-run time is reported without an offset, so the browser reads it as browser-local and displays "4:00 AM". Operators need to choose the zone their schedules run in, and the panel needs to show which zone that is.

## What Changes

- **A cobble timezone setting**: an IANA timezone name (for example `Australia/Brisbane`) that the backup and update-check schedules use. When it is unset, the host's local zone applies, as it does today. The setting is saved, takes effect without a restart, and is instance-local, so restoring a backup does not bring another instance's zone with it.
- **Cobble settings on the cobble page**: a Settings card above the existing upgrade content, with a timezone picker and a one-click "use my browser's timezone (<zone>)" option.
- **A cog in the header**: a cog right-aligned in the header opens the cobble page, as a second way in alongside the version badge. The cobble page stays out of the navigation bar.
- **A zone mismatch notice**: when the browser's zone and cobble's zone differ, the panel says so and offers to switch cobble to the browser's zone.
- **The zone is shown with schedules**: the schedule time inputs on the Updates & Backups Settings tab name the zone the time applies in. The reported next-run times are displayed in that zone.
- **Next-run times carry an offset** (**BREAKING** for API consumers that parsed the old value as naive): `next_scheduled_at` for backups and updates becomes an ISO 8601 time with the zone's UTC offset, for example `2026-10-07T04:00:00+10:00`.
- **Daylight-saving rules**: a scheduled time that falls in a spring-forward gap runs once, shifted forward by the gap, and is never skipped. A time that occurs twice at fall-back runs once, on its first occurrence, and never twice.
- **`tzdata` dependency**: cobble depends on the `tzdata` package, so timezone names resolve on hosts without a system tz database.
- **Out of scope**: changing the host's system timezone, per-schedule timezones, and changing how other timestamps (backup history, player sessions, logs) are stored. Those are already UTC-aware and continue to display in the browser's zone.

## Capabilities

### New Capabilities

- `cobble-settings`: cobble-level operator settings that are not part of the Bedrock server's configuration. The first one is the timezone. This covers how settings are stored, validated, defaulted and reported, and that they are instance-local.

### Modified Capabilities

- `maintenance-settings`: schedules run in the cobble timezone. The daylight-saving gap and repeat rules apply, and next-run times carry an offset.
- `server-backups`: the cobble timezone joins the instance-local state that a restore leaves unchanged.
- `web-ui-shell`: the header cog opens the cobble page. The cobble page shows a Settings card above the upgrade content. The schedule inputs name their zone, and the zone mismatch notice is added.

## Impact

- **Backend**: a new settings store and service for cobble settings, using a new file in the state dir. `src/cobble/schedule.py` switches to zone-aware next-run maths, with comparisons and sleeps in UTC. The `next_scheduled_at` serialisation in `src/cobble/status/tracker.py` changes. `src/cobble/api/cobble.py` gains `GET`/`PUT /api/cobble/settings`. The backup and restore path excludes the new file.
- **Frontend**: `web/src/App.tsx` (the header cog), `web/src/sections/Cobble.tsx` (the Settings card above the upgrade content), `web/src/sections/UpdatesBackups.tsx` (the zone label and zone-aware next-run display), a mismatch notice, and types in `web/src/api/client.ts`.
- **API**: new `/api/cobble/settings` endpoints. `next_scheduled_at` values gain an offset.
- **Dependencies**: `tzdata` is added to `[project] dependencies` in `pyproject.toml`.
- **Docs**: the README mentions the timezone setting and that schedules use it.
