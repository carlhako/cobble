# Tasks

## 1. Archive readers (design D1, D2)

- [x] 1.1 Add a format sniff to `worldimport/archive.py` (zip leading bytes / gzip leading bytes / refuse); verify unit tests for zip, empty zip, gzip tar, a `.zip`-named tarball, and a non-archive file
- [x] 1.2 Introduce the `Member` record and `ArchiveReader` protocol with a `ZipReader` that wraps today's zip logic (open + `testzip`, list, read, extract); verify the existing `tests/worldimport` suite passes unchanged against it
- [x] 1.3 Add `TarReader`: one streaming `r:gz` pass that builds the member list (kinds file/dir/symlink/hardlink/special) and keeps the bytes of every `level.dat` and `manifest.json`; truncated or CRC-failing input raises `ArchiveError`; verify tests with a good tarball, a truncated one, and a byte-flipped one
- [x] 1.4 Rewrite `locate_worlds`, `require_single_world`, `read_level_dat`, `world_member_names`, and `inspect` over `Member`; verify the world-location tests pass for both readers (root world, named folder, `worlds/<Name>/`, none, two worlds)
- [x] 1.5 Extend `validate_members` for tar: refuse hardlinks and special files and keep the absolute-path, `..`, and escaping-symlink refusals; verify attacker tests for each member type, failing before the change and passing after
- [x] 1.6 Implement reader extraction of a prefix into a destination that writes only regular files and dirs, never creates symlinks, and never calls `extractall`; verify a test where an in-destination symlink in the archive is not created

## 2. Kind detection and inspection (design D3)

- [x] 2.1 Classify `kind` as `backup` (tar + parseable `manifest.json` with a known format + top-level `data/` and `cobble-state/`) or `world`; verify tests: a real `capture_archive` output is `backup`; a zip with the same layout is `world`; a world-folder tarball is `world`
- [x] 2.2 Version fallback: use `manifest.bedrock_version` when `level.dat` has no readable version; verify tests for level.dat-only, manifest-only, both (level.dat wins), and neither (unknown)
- [x] 2.3 Add `kind` and, for a backup, `backup: {captured_at, bedrock_version}` to `WorldInspection.to_dict()` and the cached inspection; verify a `GET /api/import` API test for each kind
- [x] 2.4 Rename the staging file to `upload.archive` and record the detected form in the cached inspection; verify the staging tests (sweep, replace, discard, partial never held) still pass

## 3. World-only import over either format

- [x] 3.1 Make `ImportService._extract_world` and the apply-space check use the reader; verify an end-to-end service test importing a world-folder `.tar.gz` gives the same on-disk result as the equivalent zip (levelname.txt rewritten, other worlds untouched, server files not applied)

## 4. Restore core and deferred state swap (design D4, D5, D6, D8)

- [x] 4.1 Add `INSTANCE_LOCAL` to `backup/artifact.py` and an `apply_pending_state(settings)` function that swaps `<state_dir>/.pending-state/` into `state_dir`, keeping instance-local entries, writes `runtime.json` from the marker, and removes the marker and staging; verify unit tests: instance-local files untouched, others replaced, absent marker is a no-op, and an I/O failure leaves the marker and is reported
- [x] 4.2 Split `BackupService._restore` into `_restore_from(archive_path, …)`: stop, safety capture + verify, extract with the safe reader (replacing `extractall(filter="tar")`), swap `data/` live, stage `cobble-state/` + marker `{was_running, label, replaced_capture, level_name}`, and do NOT restart BDS on success; verify the existing restore tests are updated, plus a test that the live `state_dir` is untouched until `apply_pending_state` runs
- [x] 4.3 Keep the failure paths in-process (refused stop, failed capture, failed extract): no staging, BDS returned to its prior run state, no restart requested; verify the existing failure tests still pass and assert no marker exists
- [x] 4.4 Call `apply_pending_state()` in `create_app()` before `Runtime()` is constructed, and after construction re-run the gamerule `mark_restored` for the marker's level name; verify an app-factory test where a staged state appears in the stores the runtime opens
- [x] 4.5 Route `ImportService.apply()` for `kind == "backup"` through `BackupService._restore_from` using the shared version gate (newer refused, older needs confirmation), the single-world refusal, the free-space check (archive extract + capture), and import progress steps; verify service tests for each gate and a successful backup apply

## 5. Self-restart (design D7)

- [x] 5.1 Add `cobble.restart` (flag + exit hook) and `Runtime.request_restart()` (delayed request after the response); make `__main__.main()` own the `uvicorn.Server`, register a hook setting `should_exit`, and exit 75 when the flag is set; verify unit tests for the flag, the hook, and `main()`'s exit status with the server stubbed
- [x] 5.2 Call it after a successful restore from both `POST /api/backups/{name}/restore` and `POST /api/import/apply`, and add `restarting: true` to their success payloads; verify API tests assert the field and that the restart was requested only on success

## 6. Web UI (design D9)

- [x] 6.1 Import World: `accept=".zip,.mcworld,.tar.gz,.tgz"`, update the upload copy to mention a cobble backup, and render the backup kind with a "replaces everything" warning, capture time, and version; verify vitest cases for both kinds
- [x] 6.2 Add a shared "cobble is restarting" state that polls `/health` until cobble has gone away and come back, then reloads, used by Import World apply and the Backups restore; verify vitest cases with a fake fetch that fails, then succeeds
- [x] 6.3 Build the web bundle; verify `npm run build` succeeds and `npm test` is green

## 7. Verification

- [x] 7.1 Run `pytest`, `ruff check`, and `ruff format --check` on only the files touched (the clean tree already fails a whole-repo format check); verify all three are clean
- [x] 7.2 Run `openspec validate import-backup-archive --strict`; verify it passes

## 8. Release v0.7.3

- [x] 8.1 Commit the implementation on `main` with a conventional-commit message and push to `origin/main`; verify `git status` is clean and `git log origin/main -1` shows the commit
- [x] 8.2 Bump the version to 0.7.3 in `pyproject.toml`, `src/cobble/__init__.py`, and `tests/deploy/test_release_notes.py`, add a `0.7.3` CHANGELOG section (backup `.tar.gz` import as a full restore, world-folder `.tar.gz` import, cobble restarts after a restore so it runs on restored state); commit as `chore: bump version to 0.7.3` and push; verify `pytest tests/deploy` passes
- [x] 8.3 Tag `v0.7.3` and push the tag; verify the release workflow succeeds and `gh release view v0.7.3` lists the wheel

## 9. Live verification and screenshots

- [x] 9.1 Upgrade the test host (cobble-2, 10.0.1.165) to 0.7.3 (install the wheel by path); verify the header badge reads 0.7.3
- [x] 9.2 On the test host: download a backup, change a setting and the world, import the downloaded `.tar.gz`, and confirm cobble restarts, the world/settings/player history match the backup, backup history is the host's own, and the server's run state is as before; also import a world-folder `.tar.gz` and a backup with two worlds (refused); record the results in the change
- [x] 9.3 Retake all seven `docs/screenshots/` (cobble, configuration, console, dashboard, gamerules, network, updates) on the test host at 1440x900 in dark mode showing 0.7.3; commit as `docs: retake panel screenshots on v0.7.3` and push to `main`; verify the badge reads 0.7.3 in each image
