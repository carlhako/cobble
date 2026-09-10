## Why

A world that exists anywhere other than this server cannot be got onto it. An operator moving off Crafty Controller, restoring a world a friend kept a copy of, or recovering from a host rebuild has a zip file and no way to use it: cobble's only path into `data/worlds/` is a backup it captured itself. The backup format is a cobble-specific `.tar.gz` with a manifest and a checksum, so an archive from any other source — the exact archives an operator actually has — is unusable.

The machinery to do this safely already exists. M2's restore stops the server cleanly, captures the state it is about to replace, swaps directories, and starts again. Import is that same sequence with a different source, and reusing it is most of the work.

## What Changes

- **A world archive can be uploaded.** A new two-phase endpoint pair: an upload that streams an operator-supplied zip to a staging slot without buffering it in memory, and an apply that consumes the staged file. Splitting them is deliberate — it lets the operator see what cobble found in the archive before anything destructive happens, and it confines any future resumable-chunked upload to the first phase alone.
- **The world is located inside the archive, not assumed.** Bedrock worlds arrive in at least three shapes: a full server backup (`worlds/<Name>/`), a zipped world folder (`<Name>/`), and a `.mcworld`/Realms export with `level.dat` at the archive root. Cobble finds the world by structure — a `level.dat` whose sibling `db/` holds a LevelDB `CURRENT` — rather than by path. An archive containing no world, or more than one, is refused.
- **The archive is inspected before it is applied.** Cobble reports the world's name, its size, its seed, and the Bedrock version it was last opened with, read from `level.dat`. The operator confirms against what the world *is*, not against a filename.
- **Version compatibility is checked in both directions.** A world older than the installed server is upgraded in place by BDS, irreversibly, and is warned about and confirmed — the same posture restore takes. A world *newer* than the installed server may fail to load or be damaged by it, and is refused outright. Restore never has to handle the newer case; import does.
- **The import replaces the active world.** The world named by `level-name` is replaced in place. `level-name` itself does not change, so gamerule records, backups, and the configuration screen stay pointed at the same name. **This is destructive**, and the safety capture taken immediately beforehand is the undo.
- **The replaced world is captured first.** The existing verified capture runs before anything is removed, exactly as restore does. An import that fails partway leaves the operator with a restorable backup of what they had.
- **Free space is checked before the upload begins.** The import needs room for the archive, the extracted world, and the safety capture at once. Running out of space midway leaves a half-extracted world and a stopped server, so the check happens up front and refuses early.
- **An Import World section is added to the web interface.** Upload with a byte-level progress indicator, the inspection result, and a confirmation that names what is being destroyed.

Not included: importing `server.properties`, `allowlist.json`, or `permissions.json` — those are owned by the configuration and access capabilities, and an archive from another server carries another server's values. Not included: importing a world *alongside* the active one, or deleting worlds; cobble has no world-removal path today, so an import that added a directory would accumulate worlds with no way to reclaim the space. Not included: resumable chunked upload — the endpoint shape admits it later without changing what import means.

## Capabilities

### New Capabilities
- `world-import`: Bringing an externally-supplied world archive onto the server — what archives are accepted, how a world is located inside one, what is reported before the operator commits, the version compatibility rules in both directions, how the staging slot behaves, and the stop/capture/replace/start sequence that puts the world in place.

### Modified Capabilities
- `web-ui-shell`: Adds the Import World section — upload progress, the pre-import inspection, and a confirmation that identifies the world being destroyed as well as the one being installed.

## Impact

**New code** — `cobble/worldimport/` owning archive inspection (locating the world, reading `level.dat`), the staging slot, the free-space preflight, and the import sequence; an API router at `/api/import`; an `ImportWorld.tsx` section in the frontend.

**Modified code** — `cobble/runtime.py` (wire the service and its staging slot); `cobble/api/__init__.py` (register the router); `web/src/App.tsx` and `web/src/sections.tsx` (register the section); `web/src/api/client.ts` (an upload path using `XMLHttpRequest` rather than the shared `fetch` wrapper, which cannot report upload progress).

**Reused unchanged** — `capture_archive` and `verify_archive` for the safety capture, `Supervisor.maintenance_scope` / `maintenance_stop` for the stop-and-restart, `Layout.ensure_payload_symlinks`, `BackupService`'s restored-world callback (the imported `level.dat` carries its own gamerules, which must be repaired rather than adopted), and `acquisition.version.is_newer` for the comparison.

**Dependencies** — none added. `zipfile` is in the standard library; `level.dat`'s NBT header is read directly rather than through a new library, since only three fields are needed.

**Data** — adds a staging slot under `<state_dir>/`, holding at most one archive at a time. Nothing existing is migrated. The active world directory is destroyed and rebuilt by a successful import.

**Unaffected** — the backup schedule and retention, the update machinery, `server.properties` and the configuration screen, the access and player-history capabilities, and the authentication posture. `level-name` is never written.
