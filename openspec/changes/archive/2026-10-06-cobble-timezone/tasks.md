# Tasks

## 1. Dependency and settings store (backend)

- [x] 1.1 Add `tzdata` to `[project] dependencies` in `pyproject.toml` (design D7). Verify that `.venv/bin/pip install -e .` succeeds and that `python -c "import tzdata"` works in the venv.
- [x] 1.2 Add `CobbleSettingsStore` (`state_dir / "cobble_settings.json"`, tmp-file write, a malformed or missing file treated as unset) and `CobbleSettingsService` with `effective_zone()`, `host_zone_name()`, `set_timezone(name | None)` with validation, and an on-change hook (design D1, D2). Verify with unit tests:
  - set, clear and persist across a new store instance
  - an unknown name is rejected and the saved value is unchanged
  - a corrupt file reads as unset
  - host-zone detection order: `TZ`, then `/etc/timezone`, then the `/etc/localtime` symlink, then the fixed offset, with paths injected
- [x] 1.3 Add `"cobble_settings.json"` to `INSTANCE_LOCAL` in `src/cobble/backup/artifact.py` (design D1). Verify with a restore test where the backup holds `Europe/London` and the destination holds `Australia/Brisbane`: after the restore, the destination's file is unchanged, and maintenance settings are still restored from the backup.

## 2. Zone-aware scheduler (backend)

- [x] 2.1 Change `Scheduler` and `_next_after()` in `src/cobble/schedule.py` to take a UTC-aware clock and the effective zone (design D3). Build each candidate fresh from date + HH:MM with `fold=0`, advance by calendar date, and return UTC instants. Do all comparisons, the jitter grace, deferred-from and the sleep delay in UTC. Verify that the existing `tests/test_schedule.py` cases pass after porting them to an aware clock with `zone=UTC`.
- [x] 2.2 Add cross-zone tests. Verify:
  - The host clock is UTC, the zone is `Australia/Brisbane`, the schedule is daily 04:00: the next run is `18:00Z` the previous day.
  - A weekly Monday 04:00 schedule in Brisbane fires on Sunday in UTC.
  - Monthly day 31 still clamps in the zone.
- [x] 2.3 Add DST tests using `Australia/Sydney` with an injected clock stepped across the transitions. Verify:
  - Spring-forward (2026-10-04): daily 02:30 runs exactly once, at `03:30+11:00`, and 02:30 the next day.
  - Fall-back (2026-04-05): daily 02:30 runs exactly once, at the first 02:30 (`15:30Z`). Driving the loop with wakes at the second 01:xx/02:xx (`fold=1`) does not produce a second run.
  - A 04:00 schedule on both transition days runs once at 04:00 local time.
  - The sleep delay across a transition equals the true UTC difference.
- [x] 2.4 Wire the cobble settings service into `Runtime` (`src/cobble/runtime.py`) and register `scheduler.reschedule_now` as its on-change hook. Verify with a test that changing the zone while a schedule is enabled changes `backup_next_run()` without a restart.

## 3. API and status (backend)

- [x] 3.1 Serialise `next_scheduled_at` (backup and update) in `src/cobble/status/tracker.py` as the UTC instant converted to the effective zone, with its offset (design D3). Verify in `tests/status/`: Brisbane gives `2026-10-07T04:00:00+10:00`, and a run after a Sydney DST change carries the post-change offset.
- [x] 3.2 Add `GET` and `PUT /api/cobble/settings` to `src/cobble/api/cobble.py` (design D4), returning the timezone, host timezone, effective timezone and offset, and the timezone list. A PUT pushes a status update. Verify in `tests/api/`:
  - the GET shape with the zone unset and set
  - PUT with a valid name, with `null`, and with an unknown name (422 with a message, value unchanged)
  - the auth guard applies

## 4. Web UI

- [x] 4.1 Add types and client calls for `/api/cobble/settings` in `web/src/api/client.ts`, and a shared helper that formats an instant in a named zone and appends the zone name. Verify with a unit test that formats `2026-10-07T04:00:00+00:00` in `UTC` as 04:00 UTC, whatever the test's TZ.
- [x] 4.2 Add the right-aligned header cog `NavLink` to `/cobble` in `web/src/App.tsx`, with `aria-label="cobble settings"` and active styling, staying on the brand row at phone width (design D5). Verify in `web/src/test/shell.test.tsx` that activating it opens the cobble page. Check in the browser pane at 375px width that it sits right-aligned with no horizontal scroll.
- [x] 4.3 Add the `CobbleSettings` card at the top of `web/src/sections/Cobble.tsx`, above the version, notes and upgrade content. It has a filterable timezone select with "Host default (<host>)" first, the effective zone and offset, a save action with the rejection message shown, and "Use my browser's timezone (<zone>)" when the zones differ. Verify with a new `web/src/test/cobble_settings.test.tsx`:
  - the card renders before the upgrade content
  - picking and saving sends a PUT with the name
  - host default sends `null`
  - a 422 message is shown
  - the browser-zone button sets the browser's zone
- [x] 4.4 Add the mismatch check (offset sampling over 12 months, design D6) and a dismissible notice on the Updates & Backups section and in the cobble Settings card, with dismissal stored per zone pair in `localStorage` inside try/catch. Verify with unit tests:
  - `Australia/Brisbane` against `UTC` is a mismatch
  - `Australia/Melbourne` against `Australia/Sydney` is not
  - `Australia/Sydney` against `Australia/Brisbane` is, even when sampled in July
  - the notice offers the switch, a dismissal hides it for that pair, a changed pair shows it again, and throwing storage still renders the page
- [x] 4.5 In `web/src/sections/UpdatesBackups.tsx`, label each schedule time input with the effective zone, and show the backup and update next-run times in the effective zone using the helper from 4.1. Verify in `web/src/test/updates_backups.test.tsx` that, with the cobble zone `UTC` and the test running under `TZ=Australia/Brisbane`, the next run is shown as 04:00 with `UTC` named.

## 5. Docs and checks

- [x] 5.1 Update the README: the timezone setting on the cobble page, that schedules use it, that it defaults to the host's zone, and that it is not restored from backups. Verify by reading the rendered section.
- [x] 5.2 Run the full suites: `pytest`, `ruff check`, `ruff format --check` on changed files only (see the pre-existing format failure), and the web tests and build. Verify that all pass.
- [x] 5.3 Live check on cobble-2 (10.0.1.165) with the branch's release tarball:
  - With the host on UTC, the panel shows the mismatch notice from a Brisbane browser.
  - After setting `Australia/Brisbane` from the cog → cobble page, `/api/status` reports `next_scheduled_at` with `+10:00`.
  - A schedule set a few minutes ahead in Brisbane time fires at that Brisbane time.
  - Verify by recording the observed values in the change notes.

### Live check notes (5.3), cobble-2, 2026-10-06, branch tarball (cobble 0.7.4)

Host zone `Etc/UTC`; browser pane in `Australia/Brisbane`.

- **Mismatch notice**: Updates & Backups showed "Schedules run in Etc/UTC time. This browser is in Australia/Brisbane…" with a "Switch cobble to Australia/Brisbane" button. The next update check read "7 Oct 2026, 04:00 Etc/UTC", with the zone named. The old run record read 14:00 in the browser for a 04:00 UTC run, which is the original bug.
- **Setting the zone**: the switch button saved it. `GET /api/cobble/settings` returned `timezone=Australia/Brisbane`, `host_timezone=Etc/UTC`, `effective_offset=+10:00`. `/api/status` then reported `update.next_scheduled_at = 2026-10-07T04:00:00+10:00`.
- **Schedule fires in the zone**: the backup schedule was set to daily 19:21 at 19:18 Brisbane time (09:18 UTC). `backup.next_scheduled_at` read `2026-10-06T19:21:00+10:00`. The journal shows "maintenance window starting (scheduled)" at 09:21:00 UTC, which is 19:21 Brisbane. The backup completed (`last_at 2026-10-06T09:21:00Z`, `last_ok true`) and the next run was reported as `2026-10-07T19:21:00+10:00`.
- Afterwards the backup schedule was put back to disabled at 04:00. The cobble timezone on cobble-2 was left as `Australia/Brisbane`.

