# Proposal

## Why

A backup downloaded from one cobble instance cannot be brought onto another: Import World accepts only zip archives, and a cobble backup is a gzip tarball. Moving a server between hosts — the most natural use of a downloaded backup — is therefore impossible through cobble. Separately, restoring a backup today swaps cobble's state directory underneath services that keep it open or cached, so a restore leaves cobble running on the replaced state; that drift is small on the same instance but total when the backup came from another one.

## What Changes

- Import World accepts gzip-compressed tar archives (`.tar.gz` / `.tgz`) as well as zip / `.mcworld`. The container is recognised from the file's content, not its name.
- What an archive *is* is decided independently of its container:
  - A **cobble backup** (a tar archive carrying cobble's manifest, a server data directory, and a cobble state directory) is applied as a **full restore** — world, server configuration, allowlist, permissions, and cobble's own settings and history — through the same restore behaviour as a locally held backup.
  - Anything else is a **world archive** and is applied as today's world-only import, whichever container it arrived in.
- A cobble backup's recorded Bedrock version drives the version gate (newer refused outright, older confirmed). It is also used for a world archive whose level data carries no readable version.
- An archive holding more than one world is refused, for both kinds. A full restore is never ambiguous about which world the server loads.
- Uploaded archives are extracted defensively: members that escape the destination, hard links, and device or other special files are refused; symbolic links are not extracted (the server payload links are recreated by cobble itself).
- A full restore keeps the destination's instance-local state rather than adopting the source's: cobble self-upgrade state, release-check state, last-shutdown record, desired run-state record, layout-migration record, the import staging area, and backup history.
- After any full restore — local or uploaded — cobble restarts its own process so every service reads the restored state, and the Bedrock server returns to the run state it had before the restore.
- The Import World panel accepts the new file types and, for a held cobble backup, makes clear that applying it replaces everything, showing the backup's capture time and Bedrock version.
- Ship as cobble **v0.7.3**, with the panel screenshots retaken on that version.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `world-import`: archives may be gzip tar as well as zip; a cobble backup archive is recognised and applied as a full restore; a cobble backup's recorded version is used for the version gate; tar-specific unsafe members (hard links, special files) are refused and symbolic links are never extracted; the held-archive description covers a cobble backup.
- `server-backups`: a restore leaves the destination's instance-local state in place; after a restore cobble restarts so that its services run on the restored state rather than the replaced one.

## Impact

- Code: `src/cobble/worldimport/` (archive readers for zip and tar, inspection, extraction, apply routing), `src/cobble/backup/service.py` (a restore core that accepts an archive file rather than only a store entry; safe extraction for uploaded archives; instance-local exclusions; post-restore restart), `src/cobble/runtime.py` / process entry point (requesting a graceful self-restart), `web/src/sections/ImportWorld.tsx` (file types, backup-kind presentation, reconnecting after a restart), and the Backups restore flow in the web UI (reconnecting after a restart).
- API: `GET /api/import` gains an archive kind and, for a cobble backup, its manifest details; `POST /api/import/apply` for a cobble backup ends in a cobble restart.
- Deployment: none — the installed unit already restarts cobble on a non-zero exit.
- Release: version bump to 0.7.3, CHANGELOG entry, `v0.7.3` tag, retaken `docs/screenshots/`.
