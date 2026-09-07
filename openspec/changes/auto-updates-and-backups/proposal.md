## Why

M1 supervises the server but never changes what is installed and never protects the world. A Bedrock server that is not kept current eventually rejects clients on a newer game version, and a LevelDB world with no backup is one unclean shutdown or one bad update away from being gone. This is milestone M2: keep the server current on its own, and make the world recoverable.

## What Changes

- **Mutable state moves out of the version directory.** The world, `server.properties`, `allowlist.json`, and `permissions.json` are relocated to a stable `data/` directory that survives a version swap. A one-time migration moves an existing M1 installation into this layout. **BREAKING** on-disk layout change for anyone already running M1; handled automatically on first M2 start, after a backup.
- **Scheduled auto-update.** Cobble checks the vendor for a newer Bedrock version on a schedule (default around 04:00 local time) and applies it: download while the server still runs, then clean stop, pre-update backup, swap the active version, start, and health-check against the readiness signal. A failed health check rolls back to the previous version and restores the pre-update world automatically, and the failing version is quarantined so the schedule does not retry it nightly. The same sequence is available on demand from a "check for updates now" action.
- **Backups.** Cobble captures the world and its own state directory to the configured backup path — on a schedule, before every update, and on operator request — with a retention policy that prunes old backups. Each backup carries a manifest recording the Bedrock version and shutdown cleanliness.
- **Restore.** An operator can restore a captured backup: the running server is stopped, the current state is set aside, and the backup is swapped into place.
- **Status and UI.** Status gains installed-vs-available version, last/next scheduled run, last update result, and the backup list. A failed update is surfaced as an alert carrying the version attempted, the step it failed at, and the console output captured from the attempt, so an operator can see why it failed without reading journal logs. The web shell gains an "Updates & Backups" section for the version state, update history, and backup/restore controls.

Not breaking for API consumers: all additions are new routes; no existing route changes shape.

## Capabilities

### New Capabilities

- `server-updates`: Resolving whether a newer Bedrock version exists, the scheduled check, and the multi-step update state machine — pre-update backup, clean stop, install, activate, start, health check, and rollback on failure. Consumes the `server-events` readiness signal established in M1.
- `server-backups`: Capturing the world and cobble's state directory to the backup path (scheduled, pre-update, and on demand), the backup manifest, retention and pruning, and restoring a captured backup over the live installation.

### Modified Capabilities

- `installation`: Bedrock mutable state (world and config) is stored in a stable location separate from the versioned payload, is the unit of capture for backups, and survives a version swap. The per-version installation directory holds only vendor payload. A one-time migration relocates an existing installation into the new layout.
- `server-status`: Reports the latest available version alongside the installed one, the last update check and its result, the next scheduled run, and the list of captured backups; maintenance (update or restore in progress) is an observable state.
- `server-lifecycle`: An update or restore in progress blocks conflicting lifecycle actions; an update and a restore each perform a clean shutdown using the existing shutdown guarantees, and refuse to build a rollback point on a shutdown recorded as unclean.
- `web-ui-shell`: The interface presents installed-vs-available version, update history and progress, and backup and restore controls, reflecting update and backup progress without operator action.

## Impact

**New code** — a version-comparison and update-orchestration module, a backup/restore module, and an in-process scheduler, plus the routes and web section that expose them.

**Modified code** — `acquisition/layout.py` (the `data/` directory, vendor-payload symlinks, activation becomes a pure symlink swap), `runtime.py` (migration on start, scheduler wiring), `settings.py` (update schedule and mode, backup schedule, retention, backup consistency mode), the supervisor (maintenance interlock), the status tracker, and the React shell.

**On-disk layout** — `/srv/bedrock/data/` is introduced and becomes the mutable-state location; `/srv/bedrock/versions/<v>/` becomes disposable vendor payload; the previous version directory is retained as the sole rollback source because the vendor publishes only the current version.

**External dependencies** — no new services. The vendor download-links API and the resumable downloader from M1 are reused unchanged.

**Deferred** — `server.properties` and gamerule editing (M3) and the player roster (M4). M2 establishes the stable `data/` layout, the update state machine, and the backup format those milestones rely on but implements none of them.
