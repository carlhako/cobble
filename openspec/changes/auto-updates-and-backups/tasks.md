## 1. Layout foundation and payload inventory

- [x] 1.1 Determine the vendor-payload inventory by extracting a current BDS release and listing its top level; record the exact set of entries BDS expects in its working directory, and verify the list is complete by starting the server from a directory containing only those entries plus a world
      — Spiked on the live LXC against BDS 1.26.45.1. Top level recorded in `MUTABLE_ENTRIES` in `src/cobble/acquisition/layout.py`. Approach: enumerate-and-exclude — every top-level entry of the active version except `worlds/`, `server.properties`, `allowlist.json`, `permissions.json` is symlinked in, so a future payload addition is picked up with no code change. Verified: BDS launched from a directory of payload symlinks + a real `worlds/` reached "CREATING VANILLA WORLD" / "Opening level 'worlds/…/db'".
- [x] 1.2 Confirm BDS writes its world correctly when the working directory is composed of symlinks to the payload and a real `worlds/` directory; verify a world created this way loads again cleanly after a stop
      — Spiked on the live LXC from `/tmp/wdtest` (payload symlinks + a real `worlds/`). Boot 1: `CREATING VANILLA WORLD` → `Opening level 'worlds/wdtest/db'` → `Server started.`. Boot 2: `LOADING VANILLA WORLD` → `Opening level 'worlds/wdtest/db'` with no LevelDB `Corruption`/`NotFound` errors (died only on an unrelated port bind because boot 1 was left running). A single-instance clean stop→restart cycle is exercised end to end by 12.1.
- [x] 1.3 Add the mutable-state directory (`data/`) to the layout module and settings, alongside the existing bedrock root and state directory; verify the directory is created idempotently on a fresh host
- [x] 1.4 Implement creation of the vendor-payload symlinks in `data/` pointing through the `current` indirection, using the inventory from 1.1; verify each link resolves to the active version and that re-running is idempotent
- [x] 1.5 Change the supervisor to spawn BDS with its working directory set to the mutable-state directory; verify the server starts, reads `server.properties` from `data/`, and writes its world to `data/worlds/`
- [x] 1.6 Reduce version activation to replacing the `current` symlink only, with no per-version file manipulation; verify switching the active version leaves both version directories and all of `data/` unmodified
- [x] 1.7 Change first-run bootstrap to lay out `data/` and its symlinks, and to apply the fresh-install `server.properties` defaults there rather than in the version directory; verify a bootstrap from nothing produces a runnable server with an empty version directory containing no mutable state

## 2. Maintenance state and lifecycle interlock

- [x] 2.1 Add a maintenance state to the supervisor that is observable independently of the run state and records which operation is in progress; verify it is reported as absent when idle
      — `Supervisor.maintenance` / `.maintenance_step` properties + `subscribe_maintenance()`; `async with sup.maintenance_scope("updating") as handle` sets/clears it and pushes `(operation, step)` to listeners.
- [x] 2.2 Reject start, stop, and restart requests while maintenance is in progress, with an error identifying the operation; verify each rejection is distinguishable from the existing transition errors
      — new `MaintenanceInProgressError` (code `maintenance_in_progress`), distinct from `transition_in_progress`.
- [x] 2.3 Refuse to begin a maintenance operation while a lifecycle transition is in progress; verify the request fails and no maintenance state is set
      — `maintenance_scope` fails fast with `TransitionInProgressError` when `_op_lock` is held or state is STARTING/STOPPING, before setting any state.
- [x] 2.4 Suspend automatic crash restart while maintenance is in progress and route the exit to the operation in progress instead; verify a server killed during maintenance is not auto-restarted and the operation observes the exit
      — `_supervise_until_exit` routes an unexpected exit to `_maintenance_exit`; `MaintenanceHandle.wait_exit()` awaits it. No `_handle_crash`.
- [x] 2.5 Restore normal crash-restart behavior when maintenance completes or is abandoned; verify a crash after maintenance is auto-restarted as before
      — `maintenance_scope` `finally` clears the flag, re-enables auto-restart, and resets the crash window.
- [x] 2.6 Ensure cobble termination during maintenance stops the server cleanly and records the operation as interrupted rather than successful; verify a termination signal mid-operation leaves no record claiming success
      — `aclose()` sets `_closing`, stops cleanly via the existing path; `_closing` makes any later `maintenance_start()` fail so the operation's `finally` records an interrupted (not successful) outcome.

## 3. Backup capture and retention

- [x] 3.1 Define the backup artifact format and manifest carrying capture time, installed version, and shutdown cleanliness; verify a manifest round-trips and an unreadable manifest is reported rather than raising
      — `cobble/backup/artifact.py`: a backup is `cobble-backup-<UTC>.tar.gz` + a JSON sidecar written last (the completion marker). `Manifest.read` raises `BackupError`; `Manifest.try_read` returns `None` + logs.
- [x] 3.2 Implement capture of the mutable-state directory and cobble's state directory as whole directories; verify a file added to either directory after the code was written is included with no code change
      — `capture.py` tars `data/` and `state_dir/` with `recursive=True`; `data/` symlinks stored as symlinks.
- [x] 3.3 Implement cold capture: stop the server cleanly if running, capture, then return it to its prior run state; verify a capture from running ends running, a capture from stopped ends stopped, and the shutdown path is the existing clean one
      — `BackupService.capture()` uses `maintenance_scope("backing_up")` + `maintenance_stop`/`maintenance_start`.
- [x] 3.4 Record the shutdown cleanliness of the capture's own stop into the manifest; verify a capture following a forcible termination is marked unclean
      — reads `supervisor.last_shutdown.clean` after the stop into `manifest.shutdown_clean`.
- [x] 3.5 Write captures atomically so an interrupted capture is never listed as restorable; verify an interrupted capture leaves prior backups intact and is not offered for restore
      — archive written to `.partial`, renamed, sidecar last; `BackupStore.list()` enumerates sidecars only.
- [x] 3.6 Implement verification of a completed capture; verify a truncated or corrupt capture fails verification and is excluded from the restorable list
      — `verify_archive()` checks size + sha256 + full tar read + required members; `store.list()` marks failures `restorable=False`.
- [x] 3.7 Implement listing of held backups with capture time, version, size, and restorability; verify an empty destination returns an empty list with no error
- [x] 3.8 Implement retention pruning that never removes the most recent usable backup; verify exceeding the limit prunes oldest first and that a single remaining backup is never pruned
      — `BackupStore.prune(keep)`; `backup_retention` setting (default 7).
- [x] 3.9 Implement failure handling for an unwritable, full, or absent destination that records an unhealthy condition without stopping the server; verify the server keeps running and the condition is retrievable
      — `probe_destination()` pre-flight before any stop; failure sets `service.health` and records a failed `BackupOutcome`.
- [x] 3.10 Ensure a failed scheduled capture never disables future attempts; verify repeated failures leave the schedule enabled and the condition surfaced
      — the service holds no disable path; `health` persists until a capture succeeds.

## 4. Migration of an existing installation

- [x] 4.1 Implement detection of the pre-separation layout by finding world data inside the active version directory; verify detection is true for an M1-shaped installation and false for a separated one
      — `LayoutMigration.needs_migration()`: real `versions/<current>/worlds/` and no completed marker; `migrating` marker also counts (resume).
- [x] 4.2 Require the server stopped and capture a verified backup before moving anything; verify that a backup which cannot be captured or verified aborts the migration with nothing moved
      — `run()` raises `MigrationError` unless `RunState.STOPPED`; `BackupService.capture_pre_migration()` captures M1 paths into the standard `data/…` archive layout and verifies; a failed backup returns a not-migrated outcome with nothing moved.
- [x] 4.3 Implement the move of the world and operator-editable configuration into `data/`, followed by creation of the payload symlinks; verify the server starts against the separated layout afterwards with the world intact
      — per-file `os.replace` into `data/` (M1 config is authoritative on the first pass) + `ensure_payload_symlinks()`.
- [x] 4.4 Make the migration idempotent and resumable, recording completion so it never runs twice; verify an interrupted migration completes on the next start with no world data lost
      — marker states `migrating` → `migrated`/`fresh`; the `migrating` marker is written before the first move so a partial run always resumes; `_merge_move` is per-child and skips files already at the destination; a resume takes no second backup.
- [x] 4.5 Wire migration into startup ahead of any server start, skipping it for an already-separated or freshly bootstrapped installation; verify a fresh install performs no migration and an M1-shaped one migrates exactly once
      — `Runtime._migrate_layout()` runs after bootstrap, before `supervisor.restore()`; `bootstrap_if_needed` defers `data/` seeding for an M1-shaped install so it never races the migration.

## 5. Restore

- [x] 5.1 Implement restore of a selected backup: stop cleanly, capture the state being replaced, put the backup contents in place, then start; verify the world after restore matches the captured one
      — `BackupService.restore()` under `maintenance_scope("restoring")`; `_extract_over_layout` swaps `data/` and `cobble-state/` from the archive (cross-fs safe via `shutil.move`).
- [x] 5.2 Refuse a restore when the server cannot be stopped cleanly, leaving existing state untouched; verify the failure is reported and nothing was replaced
      — checks `last_shutdown.clean` after `maintenance_stop`; on unclean it restarts the old server and returns a failure before any capture/replace.
- [x] 5.3 Surface a warning when a backup's recorded version is older than the installed version, without refusing the restore; verify the warning is present and the restore still proceeds on confirmation
      — returns `RestoreOutcome(needs_confirmation=True, warning=…)`; `restore(..., confirm_old_version=True)` proceeds.
- [x] 5.4 Handle a restore that fails partway, keeping the capture of the replaced state available; verify the replaced state remains recoverable after a simulated mid-restore failure
      — the pre-restore safety capture is taken and verified before anything is overwritten; its archive name is returned as `replaced_capture` on failure. (Also fixed: microsecond-precision archive stamps so a same-second pre-restore capture can't collide with the source.)

## 6. Update state machine

- [x] 6.1 Implement comparison of the vendor's current version against the installed one, reporting availability and reusing the existing non-raising resolver; verify an unreachable vendor source is surfaced without raising and without attempting an update
      — `UpdateService.check()` uses `try_resolve_current_version` + `acquisition/version.py` (`is_newer`); `None` → `UpdateCheck.error`, `apply()` → `aborted`, server untouched.
- [x] 6.2 Implement acquisition of a new version while the server keeps running, reusing the existing downloader and extractor; verify the server is never stopped during acquisition and a failed download leaves the active version unchanged
      — `install_version()` runs before `maintenance_scope`; `InstallError` → `aborted` (step `acquire`), active version unchanged.
- [x] 6.3 Implement the maintenance window: clean stop, then abort and restart the previous version if the shutdown is recorded unclean; verify an unclean stop abandons the update before the active version changes
- [x] 6.4 Take and verify the pre-update backup inside the window, aborting and restarting the previous version if it fails; verify an unverifiable backup abandons the update with the active version unchanged
      — `BackupService.snapshot_now("pre-update")` inside the update's own scope.
- [x] 6.5 Activate the new version and await the readiness signal within the readiness timeout; verify activation alone is not treated as success
      — `maintenance_start()` awaits readiness; a `SupervisorError` → rollback.
- [x] 6.6 Implement the post-readiness grace window that treats an early exit as a failed update; verify a server that becomes ready then exits inside the window is treated as failed
      — `asyncio.timeout(update_grace_seconds)` around `handle.wait_exit()`; an exit resolves it → rollback (step `grace-window`).
- [x] 6.7 Implement automatic rollback: reactivate the previous version, restore the world from the pre-update backup, and start; verify the rollback runs with no operator action and the world matches the pre-update capture
      — `_rollback()`: `set_active_version(previous)` → `restore_contents_now(pre_archive)` → `maintenance_start()`.
- [x] 6.8 Always restore the world on rollback, including when the failed version never signalled readiness; verify the world left on disk by the failed version is not retained as authoritative
      — `_rollback` always restores from the pre-update backup regardless of the failure step.
- [x] 6.9 Implement the terminal state when rollback cannot start the previous version: cease automatic action, change nothing further, surface as needing intervention; verify no further automatic starts occur
      — `_terminal` flag set; `apply()` returns `terminal` immediately while set; cleared only by `clear_failed()`.
- [x] 6.10 Implement the record of a version that failed an update and skip it on subsequent automatic checks; verify a repeated check of the same version attempts no update and reports the reason
      — `UpdateStateStore.add_failed`; `check()`/`apply()` report `skipped` for a quarantined available version.
- [x] 6.11 Attempt an update normally when the vendor publishes a version other than the failed one, and allow an operator to clear the record; verify both paths lead to an attempt
      — a different `available` version is not quarantined → attempted; `clear_failed(version|None)` also lifts `_terminal`.
- [x] 6.12 Retain the failed version's files and record the version attempted, the failing step, and the captured output; verify the diagnostics are retrievable after a cobble restart without consulting system logs
      — version dirs are never removed on failure; `state_dir/updates.json` persists `failed_versions` (with `output_tail` from `console.snapshot()`) and `last_result`; `diagnostics()` exposes them.
- [x] 6.13 Implement pruning that retains the replaced version as the rollback source and removes older installations; verify the rollback source is never pruned
      — `Layout.prune_versions({new, previous})` after a success; anything ≥ the oldest kept version is left alone.
- [x] 6.14 Guard against concurrent updates and reject an update requested while one is in progress; verify the second request fails with a distinguishable error
      — `UpdateService._busy` → `UpdateConflictError` (code `update_in_progress`).

## 7. Scheduling

- [x] 7.1 Implement an in-process scheduler that computes the next run in local time; a window missed while cobble was down is skipped until the next day (no catch-up — waking hours later to stop the server at an unexpected time is worse than waiting one day); verify the next run time is correct across a daylight-saving boundary
      — `cobble/schedule.py` `Scheduler`: asyncio loop, `next_run()` from naive local time recomputed each wake (≤15min sleeps); the pending target runs only within a 30-minute jitter grace of its time, otherwise it is skipped and the next run is the following day. No state file.
- [x] 7.2 Run the nightly window as a single ordered sequence of backup then update check; verify the server is stopped only once when both are due
      — `_run_window`: if an update is available it runs `update.apply` (whose verified pre-update backup is the nightly backup — one stop); otherwise a standalone `backup.capture`.
- [x] 7.3 Expose the next scheduled run time and make the schedule configurable and disableable; verify a disabled schedule performs no automatic work while on-demand operations still function
      — `maintenance_time` (empty disables), `backup_enabled`, `update_enabled` settings; `next_run()` returns `None` when disabled; `run_now()` still works.
- [x] 7.4 Implement on-demand update check and on-demand backup that reuse the scheduled sequences; verify both produce the same behavior as a scheduled run
      — `Scheduler.run_now()` calls the same `_run_window`; the API also exposes `update.check`/`update.apply`/`backup.capture` directly (same methods the window uses).

## 8. HTTP interface

- [x] 8.1 Add update routes (check, apply, clear failed-version record) under the existing single router and dependency-injection point; verify the generated OpenAPI schema lists them
      — `api/updates.py`: `POST /api/updates/check|apply|clear-failed`, `GET /api/updates/diagnostics`, all under the `auth_guard` DI point.
- [x] 8.2 Add backup routes (list, capture, restore) with structured errors for conflicting operations; verify each rejection case returns a distinguishable error code
      — `api/backups.py`: `GET/POST /api/backups`, `POST /api/backups/{archive}/restore`; conflicts → 409 `{error: "backup_in_progress" | "update_in_progress" | "maintenance_conflict"}` via `_shared.conflict()`.
- [x] 8.3 Extend the status payload and status stream with version, update, backup, and maintenance fields; verify a connected client is pushed maintenance step changes without polling
      — `StatusSnapshot` gains `maintenance`, `version_info`, `update`, `backup`; `StatusTracker` subscribes to `supervisor.subscribe_maintenance` → `_emit()`, so `/api/status/stream` pushes on every step change.
- [x] 8.4 Add a route exposing failed-update diagnostics including captured output; verify the output of a failed update is retrievable through it
      — `GET /api/updates/diagnostics` → `UpdateService.diagnostics()` (version attempted, failing step, captured `output`), null before any failure.

## 9. Status

- [x] 9.1 Report the installed and available versions, including the unknown case before any successful check; verify no error is raised when no check has succeeded
      — `version_info`: `{installed, available, up_to_date}`; `available`/`up_to_date` are `null` (unknown) until a check succeeds.
- [x] 9.2 Report last update check, most recent update outcome, next scheduled check, and whether the available version is being skipped; verify each field after a successful, a failed, and a skipped update
      — `update`: `{last_check_at, last_result{status,at,detail,from_version,to_version,step}, next_scheduled_at, skipping, terminal}`.
- [x] 9.3 Report last backup time and outcome, next scheduled backup, and the unhealthy condition when backups are failing; verify the unhealthy condition appears and clears
      — `backup`: `{last_at, last_ok, next_scheduled_at, unhealthy, count}`; `unhealthy` mirrors `BackupService.health` and clears on the next successful capture.
- [x] 9.4 Report maintenance activity as a value distinct from run state, including the current step; verify the run state continues to describe the server process while maintenance is in progress
      — `maintenance`: `{operation, step}` or `null`, independent of `run_state`.

## 10. Web interface

- [x] 10.1 Add the "Updates & Backups" section using the shell's existing extension point; verify no shell restructuring is required to add it
      — one entry in `web/src/sections.tsx`; `App.tsx` untouched.
- [x] 10.2 Present installed and available version, up-to-date state, and a check-for-updates action; verify the result is reflected without a refresh
      — `VersionPanel` reads `status.version_info`/`status.update` from the shared SSE status; "Check for updates" + "Update to X" call the API and the pushed status updates the panel.
- [x] 10.3 Present the failed-update alert with version attempted, failing step, and captured output; verify the output is readable without host access
      — `FailedUpdateAlert`: version/step/detail from `status.update.last_result`, "Show captured output" fetches `/api/updates/diagnostics` into a `<pre>`.
- [x] 10.4 Present the skipped-version indication and an action to clear the record; verify clearing it allows a subsequent attempt
      — `status.update.skipping` → notice + "Clear record" → `POST /api/updates/clear-failed`.
- [x] 10.5 Present the rollback-failed state as requiring operator intervention; verify it is visually distinct from an ordinary failed update
      — `RollbackFailedAlert` on `status.update.terminal`, `.panel.is-critical` (distinct from `.is-error`).
- [x] 10.6 Present the backup list, a capture action, and a restore action gated by an explicit confirmation naming the backup and stating that current state is replaced; verify restore cannot be triggered without that confirmation
      — `BackupsPanel` table + "Capture backup now"; "Restore" opens an `alertdialog` naming the archive/time and stating "This replaces the current world and cobble state"; the API call fires only from the dialog's confirm button (plus a second dialog for the older-version warning).
- [x] 10.7 Reflect maintenance progress and its current step, withholding conflicting lifecycle controls while it runs; verify opening the interface mid-operation shows the operation and its step
      — `MaintenanceBanner` + a banner on the Dashboard; `ServerControls` gets `disabled` while `status.maintenance` is set; the Updates/Backups action buttons disable too.
- [x] 10.8 Present the unhealthy backup condition with its reason; verify it appears when the destination is unwritable
      — `status.backup.unhealthy` → `.panel.is-error` "Backups are failing" with the reason.

## 11. Configuration and documentation

- [x] 11.1 Add settings for update schedule and enablement, backup schedule and enablement, retention, and the grace window, each with a documented default; verify cobble still loads with no config file present
      — `maintenance_time` ("04:00"), `backup_enabled`/`update_enabled` (true), `backup_retention` (7), `update_grace_seconds` (60), each a Field with a description; `test_defaults_load_with_no_config_file` asserts them. Per design.md D7 the backup and update schedules share the one nightly `maintenance_time` (two independent schedules were rejected).
- [x] 11.2 Document the new settings and the `data/` layout in the README, including that `/backup` is now actively used; verify the documented layout matches what a fresh install produces
      — README "Filesystem layout" + "Configuration" updated; `test_fresh_install_layout_matches_the_documented_layout` checks the produced tree.
- [x] 11.3 Document the migration and the manual steps required to revert to a pre-separation cobble release; verify the documented revert restores a runnable M1-shaped installation
      — README "Reverting to a pre-M2 (M1) cobble release"; `test_documented_revert_restores_a_runnable_m1_installation` runs those exact steps and asserts an M1-shaped, startable install.

## 12. End-to-end verification

- [x] 12.1 Verify the migration on a live LXC carrying a real world: backup taken, world relocated, server starts against the separated layout with the world intact and players able to rejoin
      — Run on cobble-2 (10.0.1.165), Debian 13 LXC, from cobble 0.1.5 (M1-shaped, world in `versions/1.26.45.1/worlds/`) → deployed 0.2.0. First start: `pre-separation layout detected` → verified backup `cobble-backup-20260907T223949…tar.gz` → `migration complete` → `restoring previously-running server`. Verified: `data/` holds `worlds/` + `server.properties`/`allowlist.json`/`permissions.json` as real files with the operator's M1 content, every vendor entry symlinked through `current`; version dir carries no mutable state; `layout_migration.json` = `migrated`; BDS runs with `cwd=/srv/bedrock/data`; console shows `LOADING VANILLA WORLD` → `Opening level 'worlds/Bedrock level/db'` → `Server started.` on port 19132; the pre-migration backup's world matches the pre-migration on-disk world (8 frozen LevelDB files + `levelname.txt` identical; `level.dat` differs only by BDS's normal clean-shutdown rewrite). Restart → no re-migration, no extra backup. In-game player rejoin still to be confirmed by the operator against 10.0.1.165:19132.
      — Observed during the first live run: the old missed-window catch-up ran an immediate backup+restart on a mid-day upgrade. Fixed in the same milestone — catch-up removed entirely (7.1): a window is only run within a 30-minute jitter grace of its scheduled time, otherwise skipped until the next day.
- [ ] 12.2 Verify a successful scheduled update end to end: download occurs with the server running, the window stops and restarts it once, the new version becomes ready, and the previous version is retained
- [ ] 12.3 Verify a failed update rolls back automatically by activating a deliberately broken version: the previous version is restored and started, the world matches the pre-update capture, and the diagnostics are visible in the interface
- [ ] 12.4 Verify the failed version is not retried on the next scheduled run, and that publishing a different version resumes normal updates
- [ ] 12.5 Verify a scheduled backup, its retention pruning across several runs, and a restore of a captured backup returning the world to its captured state
- [ ] 12.6 Verify backup failure handling with the destination unmounted: the server keeps running, the condition is surfaced in the interface, and the schedule still attempts the next run
- [ ] 12.7 Verify the maintenance interlock on a live server: lifecycle actions are refused during an update, crash restart does not fire, and both resume normally afterwards
