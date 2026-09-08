## Why

The Configuration and Gamerules sections present long, flat lists of settings with no way to jump to one by name — an operator hunting for a single key scrolls the whole list. The Backups section lets an operator capture and restore, but gives no way to take a copy of a backup off the host for safe-keeping or inspection. Separately, operators have asked whether their player history and roster survive a backup: they do, but nothing in the interface or the spec says so plainly.

## What Changes

- Add a filter field at the top of the **Configuration** section that narrows the visible settings list as the operator types, matching on setting key and description. Status and pending-change information is never hidden by the filter.
- Add the same filter field at the top of the **Gamerules** section, narrowing the active world's rule list. The preferred-defaults editor is out of scope for this change.
- Add a **Download** control to each row of the backup list in the **Updates & Backups** section that retrieves that backup as a single file.
- Add an HTTP route that serves a held backup archive as a file download, with the archive name validated against the backup store so nothing outside the backup directory can be fetched.
- Document, in the backups spec, that a captured archive includes cobble's durable state — the player history and roster database among it — in an internally consistent form. This is existing behavior (the database is quiesced before capture); the change makes it an asserted requirement rather than an implementation detail.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `server-backups`: add a requirement that a held backup is retrievable as a single file on operator request; add a scenario to the capture requirement asserting that cobble's state database is captured in a self-consistent form.
- `web-ui-shell`: add a requirement that the Configuration and Gamerules sections offer a filter that narrows their setting/rule lists without hiding status or pending information; add a requirement that the backups list offers a per-backup download control.

## Impact

- **Web** (`web/src/`): a shared `FilterBar` component; wiring into `sections/Configuration.tsx` and `sections/Gamerules.tsx`; a Download link per row in `sections/UpdatesBackups.tsx`; a `backupsDownloadUrl` helper in `api/client.ts`.
- **API** (`src/cobble/api/backups.py`): a new `GET /backups/{archive}` route returning a `FileResponse`, reusing `BackupStore.get()` for name validation and existence.
- **Backend**: no change to capture or restore logic; `capture.py` already quiesces `cobble.db` before archiving.
- No new dependencies. No breaking changes. The download route is read-only and operates on completed, immutable archives.
