# Design

## Context

See proposal.md for motivation; the requirements are in `specs/world-import` and `specs/server-backups`.

Current state that shapes the approach:

- **World import** (`src/cobble/worldimport/`) is zip-only throughout. `archive.py` opens, tests, lists, and reads `level.dat` via `zipfile`. `service._extract_world` streams zip members. The staging slot names the held file `upload.zip`. The upload arrives as a raw request body with no file name.
- **A cobble backup** (`backup/capture.py`) is a gzip tar with top-level `data/`, `cobble-state/`, and `manifest.json` (format, captured_at, bedrock_version, shutdown_clean, contents). `data/` carries symlinks to the vendor payload, which `Layout.ensure_payload_symlinks()` recreates.
- **Restore** (`BackupService.restore/_restore`) accepts only a store entry. It extracts with `tarfile.extractall(filter="tar")`, which suits cobble-made archives but does not refuse links or special files, and needs Python ≥3.11.4 while the project allows any 3.11. It then swaps `data/` and `cobble-state/` while cobble keeps running.
- **Cobble's state is live while it runs.** The player-history database is a long-lived sqlite connection. Maintenance, update, and gamerule state are cached. `Runtime.shutdown()` flushes and closes several stores. `runtime.json` (desired run state) and `last_shutdown.json` sit inside `state_dir`. On termination, `Supervisor.aclose()` rewrites `runtime.json` if the server is running.
- **Deployment.** `cobble.service` has `Restart=on-failure` with `RestartSec=3`, so a non-zero exit is restarted. `create_app()` constructs `Runtime`, and the constructors open their stores.

## Goals / Non-Goals

**Goals:**
- One reader abstraction so inspection, validation, and extraction are written once for zip and tar.
- A restore core that can be driven by a store entry or by a held upload, with identical stop / safety-capture / replace / start semantics.
- Cobble never runs on, or writes over, `cobble-state` that it did not load at startup.

**Non-Goals:**
- Zip-form cobble backups, and tar compressions other than gzip in the UI and docs (`tarfile` `r:*` may accept them silently; they are not promised).
- Merging state from two instances. A restore is a replacement, minus the instance-local list.
- Choosing among several worlds. More than one world is refused.
- Changing the systemd unit.

## Decisions

### D1. Recognise the container by its leading bytes

`PK\x03\x04` (also `PK\x05\x06` for an empty zip) means zip; `\x1f\x8b` means gzip tar; anything else is refused as "not a readable archive". The staging slot keeps a single neutral name (`upload.archive`), and the detected form is recorded in the cached inspection.
*Alternative:* the file extension from a header. Rejected: the upload is a raw stream, and the spec requires content to win over the name.

### D2. A neutral `ArchiveReader` over zip and tar

`worldimport/archive.py` gains a small protocol: `members() -> list[Member]` (normalised name, size, kind ∈ {file, dir, symlink, hardlink, special}, link target), `read(name) -> bytes` for small members, and `extract(prefix, dest, *, skip_symlinks)`. It has two implementations:
- `ZipReader` wraps the existing zip logic. `testzip` remains its integrity check.
- `TarReader` makes one streaming pass in `r:gz` mode to build the member list and keep the bytes of every `level.dat` and `manifest.json` (all tiny). Reading to EOF verifies gzip's CRC, so this pass is also the integrity check. Extraction is a second streaming pass that writes regular files itself via `extractfile()` and never calls `extractall`.

`locate_worlds`, `require_single_world`, `read_level_data`, `validate_members`, and `inspect` are rewritten against `Member` and stay format-agnostic. Two decompressions of a large tar are accepted; the inspection is cached.

### D3. Kind is decided by contents; the gate is the same for both kinds

`kind = "backup"` when the reader is a tar and the top level holds `manifest.json` (parseable, `format` known), `data/`, and `cobble-state/`. Otherwise `kind = "world"`. Both kinds run `require_single_world` over the whole archive, so a backup with two worlds under `data/worlds/` is refused, matching the user's choice to keep this simple. The version used by the gates is `level.dat`'s `lastOpenedWithVersion`, falling back to `manifest.bedrock_version`. This fallback applies to both kinds (a world-kind tar can still carry a manifest).

### D4. Safe extraction for anything uploaded

`validate_members` refuses absolute paths, `..` escapes, hard links, and special files anywhere in the parts that will be extracted. Symlinks are refused if they escape the destination (existing zip behaviour) and are never created. For a backup, `ensure_payload_symlinks()` restores the payload links afterwards. The same validator and extractor replace `extractall(filter="tar")` in the restore core, so local restores also stop depending on the tarfile filter API.

### D5. The restore core takes a file, and the state swap is deferred to startup

`BackupService._restore` is split into `_restore_from(archive_path, *, label, recorded_version)`. `restore(name)` resolves a store entry and calls it; `ImportService.apply()` calls it for `kind == "backup"`, and keeps its existing world-only path for `kind == "world"`. Sequence:

```
 live cobble                                         next cobble start
 -----------                                         -----------------
 stop BDS (clean or refuse)                          create_app():
 safety capture of data/ + cobble-state/ (verify)      apply_pending_state() --+
 extract archive -> <bedrock_root>/.restore-staging     before Runtime() is    |
 swap staged data/ -> data/        (BDS stopped,        constructed            |
                                    safe live)                                 |
 move staged cobble-state/ -> <state_dir>/.pending-state/                       |
 write <state_dir>/.pending-state.json                                          |
   {was_running, label, replaced_capture}                                       |
 respond to the HTTP request                                                    |
 request self-restart (exit 75) ---------------> systemd restarts ------------- +
                                                     swap .pending-state into state_dir,
                                                       keeping INSTANCE_LOCAL entries
                                                     write runtime.json = was_running
                                                     delete marker + staging
                                                   Runtime() opens the restored stores
                                                   bootstrap -> supervisor.restore()
                                                     starts BDS iff was_running
```

Why defer: `Runtime.shutdown()` closes and flushes stores and `Supervisor.aclose()` rewrites `runtime.json`. A swap done live could be overwritten during that shutdown, and the open sqlite connection would keep writing to the unlinked old database. Swapping before anything is constructed removes both hazards.
*Alternative:* add `reload()` to every stateful service. Rejected: wide, and a new store added later would silently be missed.
*Alternative:* swap live, then restart. Rejected for the clobbering above.

`data/` is swapped live because nothing in cobble holds it open while BDS is stopped. The restored `server.properties` names the world for the gamerule repair. That repair's marker is stored in `cobble.db`, which is staged, so it cannot be set during the live restore. Instead the pending marker carries the level name, and `Runtime.after_pending_restore()` calls `gamerules.mark_restored` once the restored stores are open.

Once a restore has staged state, `BackupService` refuses any further capture or restore, and the import service refuses any apply, until the restart. A capture never includes `import-staging/` (a held upload) or the pending slot. Without that exclusion, a backup import's own safety capture would bundle the uploaded backup inside itself.

### D6. Instance-local entries stay with the destination

One tuple in `backup/artifact.py`, `INSTANCE_LOCAL = ("upgrade", "upgrade_pending.json", "upgrade_last.json", "release_check.json", "last_shutdown.json", "runtime.json", "layout_migration.json", "import-staging", "backup_history.json")`, plus `.pending-state*` itself. The startup swap removes everything else under `state_dir` and moves the staged entries in, skipping these names. Capture is unchanged: backups still contain these files, so older cobble versions can still restore them whole. Exclusion is a restore-time rule.

### D7. Self-restart

`cobble.restart` holds a process-wide "restart requested" flag and an exit hook. `__main__.main()` builds the `uvicorn.Server` itself and registers a hook that sets `server.should_exit`, which runs uvicorn's normal graceful lifespan shutdown without involving a signal. `Runtime.request_restart()` schedules the request about 1 s later, after the apply response has been flushed. When `server.run()` returns with the flag set, `main()` exits with status 75 (`EX_TEMPFAIL`), and `Restart=on-failure` brings cobble back.
*Rejected:* signalling the process with `SIGTERM`. uvicorn (≥0.29) re-raises a captured signal after shutdown, so the process would die by SIGTERM, and systemd counts SIGTERM as a clean exit that `on-failure` does not restart.
With no hook registered (tests, or an embedding without `main()`), the request is logged and the flag is set. A dev run that is not under systemd simply exits and logs that cobble must be started again; the pending swap still applies on the next start. Tests drive `apply_pending_state()` and the flag directly.

### D8. A failed restore does not restart

If the stop is refused, the safety capture fails, or extraction fails, nothing is staged into `.pending-state`. Cobble returns BDS to its prior run state in-process, exactly as today, and no restart is requested. If the startup swap itself fails (I/O error), cobble logs it, leaves the marker, starts anyway on whatever state is present, and surfaces the condition in backup health, naming the safety capture.

### D9. API and UI

`GET /api/import` adds `inspection.kind` (`"world" | "backup"`) and, for a backup, `inspection.backup = {captured_at, bedrock_version}`. `POST /api/import/apply` and `POST /api/backups/{name}/restore` add `restarting: true` on success. The Import World panel uses `accept=".zip,.mcworld,.tar.gz,.tgz"`, updates its copy, and for a backup shows a "replaces everything" warning with the capture time and version. On `restarting` it shows a "cobble is restarting" state and polls `/health`, as the self-upgrade does. It counts cobble as back only after it has been seen to go away, so the old process answering just before it exits is not mistaken for the new one. It then reloads the page. The Backups restore flow gets the same restarting state.

## Risks / Trade-offs

- [Cobble isn't run under systemd and doesn't come back] → Dev-only; it is logged clearly, and the pending swap applies on the next start whenever that is.
- [Swapping `cobble-state` while the old process still has files open] → The swap runs in the new process before `Runtime()` exists. The old process has exited.
- [Crash between staging and restart] → The marker plus `.pending-state/` are applied at the next start. The safety capture taken before anything changed remains restorable.
- [Large tar uploads decompress twice] → Accepted (user confirmed). The inspection is cached.
- [A backup from a much older cobble lacking some state files] → The swap moves only what is present. Missing stores are created fresh by their constructors, as on a new install.
- [The server.properties from the source binds a port already used on the destination host] → Out of scope. It is the operator's configuration, visible on the Configuration and Network pages after the restore.
- [Retention prunes just after the restore] → Unchanged behaviour. The safety capture is the newest entry and is never pruned first.

## Migration Plan

No data migration. Ship as v0.7.3: bump `pyproject.toml`, `src/cobble/__init__.py`, and `tests/deploy/test_release_notes.py`, add a CHANGELOG section, push `main`, then push tag `v0.7.3` (release workflow). Deploy to the test host (cobble-2, 10.0.1.165) and verify both directions: a backup downloaded there and imported back, a world-folder `.tar.gz` import, and a local restore restarting cleanly. Then retake the seven `docs/screenshots/` at 1440x900 in dark mode on 0.7.3. Rollback: install v0.7.2. A restore never alters a backup archive, so nothing on disk needs undoing.
