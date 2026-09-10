## 1. Archive inspection

- [x] 1.1 Create the `cobble.worldimport` package with an `ArchiveError` and a module that opens a zip and refuses one that is not a readable archive or fails `testzip()`; verify unit tests cover a truncated file, a non-zip file, and a valid zip
- [x] 1.2 Implement the world locator per design.md D5 — find every `level.dat` whose sibling `db/` contains `CURRENT`, and return the world root prefix; verify unit tests over three synthesised archives covering `worlds/<Name>/`, `<Name>/`, and a root-level `.mcworld` layout
- [x] 1.3 Refuse an archive with zero located worlds and one with more than one, each with a distinct reason naming the count; verify tests assert both refusals and that neither reaches extraction
- [x] 1.4 Implement the `level.dat` reader for `LevelName`, `RandomSeed`, and `lastOpenedWithVersion` per D5, returning `None` for any field it cannot parse; verify a test reads the fixture world and asserts version `1.26.43.1` and seed `-7302393117572340386`, and a second test asserts a truncated `level.dat` yields all-`None` without raising
- [x] 1.5 Implement member validation per D7 — refuse absolute paths, refuse members normalising outside the destination, refuse links whose targets escape it; verify unit tests cover `../` traversal, a leading `/`, and an escaping symlink member, each refusing the whole archive
- [x] 1.6 Produce an inspection result carrying the world name, uncompressed size, seed, last-opened version, and the names of any non-world server files present (`server.properties`, `allowlist.json`, `permissions.json`); verify a test against the reference archive reports the world plus all three extra files

## 2. The staging slot

- [x] 2.1 Add a staging slot under `<state_dir>/import-staging/` with a single fixed archive path per D8, created on demand; verify a test asserts the directory is created lazily and that the layout's other directories are untouched
- [x] 2.2 Implement write-to-`.partial`-then-rename so an interrupted upload is never held as applicable; verify a test asserts a `.partial` left behind is not reported as a held archive and does not overwrite an archive already held
- [x] 2.3 Implement replace-on-new-upload, clear-on-apply, and discard, each reclaiming the storage; verify tests assert the slot holds at most one archive and is empty after each of the three
- [x] 2.4 Sweep the staging slot on startup so nothing survives from a previous run; verify a test seeds an archive and a `.partial`, constructs the runtime, and asserts both are gone
- [x] 2.5 Cache the inspection result alongside the held archive so repeated reads do not rescan a multi-gigabyte zip; verify a test asserts a second inspect does not reopen the file

## 3. Free-space preflight

- [x] 3.1 Implement the upload-time check — refuse before reading the body when free space cannot hold the declared archive size, per D9; verify a test with a stubbed free-space probe asserts the refusal and that nothing is written
- [x] 3.2 Implement the apply-time check — the located world's uncompressed size plus an estimate of the safety capture, with the margin from D9; verify a test asserts the refusal happens before any stop is requested of the supervisor
- [x] 3.3 Report insufficient space with the required and available amounts; verify a test asserts both figures appear in the error

## 4. The import sequence

- [x] 4.1 Implement the version comparison per D6 using `acquisition.version.is_newer` — refuse a newer world unconditionally, return a needs-confirmation outcome for an older one, proceed on equal or unknown; verify unit tests cover all four cases including that `confirm_old_version` does not override the newer refusal
- [x] 4.2 Implement the import as a `maintenance_scope` mirroring `BackupService._restore` — stop cleanly, refuse and restart on an unclean stop, capture and verify the replaced state, replace the world, restart; verify a test with a fake supervisor asserts the ordering and that an unclean stop leaves the world untouched
- [x] 4.3 Abandon the import when the safety capture fails or does not verify, before any file is removed; verify a test with a failing `verify_archive` asserts the world directory is byte-identical afterwards
- [x] 4.4 Extract only the located world subtree into `data/worlds/<level-name>/`, replacing its contents, and rewrite `levelname.txt` to the destination name per D2; verify a test imports the reference archive into a world named `MyWorld` and asserts `levelname.txt` reads `MyWorld` and that the 243 MB `bedrock_server` member was never written
- [x] 4.5 Leave `level-name` unwritten and other worlds untouched; verify a test with three worlds present asserts only the selected one changed and `server.properties` is unmodified
- [x] 4.6 Call the restored-world callback after a successful import so gamerules are reasserted rather than adopted, per D2; verify a test asserts the callback fires with the current level-name and that the imported world's differing gamerule values are not adopted
- [x] 4.7 Re-establish the vendor-payload symlinks after the replace and return the server to its prior run state on every exit path; verify tests cover success, capture failure, and mid-extract failure, each asserting the run state matches what it was
- [x] 4.8 Report a mid-extract failure with the safety capture's name; verify a test asserts the capture appears in the error and is listed as restorable afterwards
- [x] 4.9 Share the busy guard with backup, restore, and update so no two overlap, raising the existing conflict error; verify tests assert an import during a backup and a backup during an import are both refused with the operation named
- [x] 4.10 Report import stages through the maintenance handle — stopping, capturing, putting the world in place, starting; verify a test collects the emitted steps in order

## 5. The programmatic interface

- [x] 5.1 Add the `/api/import` router behind `auth_guard` with the four routes from D1; verify a test asserts every route requires authentication
- [x] 5.2 Implement `POST /api/import/upload` reading `request.stream()` to disk per D3, with no multipart dependency added; verify a test uploads a synthetic 200 MB body and asserts peak process memory does not scale with it
- [x] 5.3 Implement `GET /api/import` returning the inspection result or an empty state, and `DELETE /api/import` discarding the slot; verify tests cover both with and without an archive held
- [x] 5.4 Implement `POST /api/import/apply` taking `confirm_old_version` and returning an outcome shaped like `RestoreOutcome`; verify tests cover success, needs-confirmation, the newer-version refusal, and the conflict rejection
- [x] 5.5 Register the router in `cobble/api/__init__.py` and wire the service and staging sweep in `runtime.py`; verify the app starts and the routes appear in the OpenAPI schema

## 6. The Import World section

- [x] 6.1 Add the `Import World` route, nav entry, and section registration in `App.tsx` and `sections.tsx`; verify a test asserts the nav item renders and the route resolves
- [x] 6.2 Add the upload client using `XMLHttpRequest` per D10, exposing byte progress, confined to one function with the exception documented in a comment; verify a test asserts progress callbacks fire and that other import calls still go through the shared wrapper
- [x] 6.3 Build the upload panel with a file chooser, a progress indicator, and a statement that importing replaces the current world; verify a test asserts progress advances and that a failed upload shows its reason with a retry available
- [x] 6.4 Build the inspection panel showing world name, size, seed, and last-opened version, and reporting any non-world server files as present-but-not-imported; verify a test renders the reference archive's inspection and asserts every field
- [x] 6.5 Show the refusal reason and offer no apply action when the archive holds no world, holds several, or is unreadable; verify tests cover all three
- [x] 6.6 Build the confirmation naming the world being installed, the world being replaced, the stop and restart, and the safety capture; verify a test asserts nothing is applied until confirmed and that declining leaves the archive held
- [x] 6.7 Add the second confirmation for an older world and the non-overridable refusal for a newer one, following the existing restore confirmation pattern; verify tests cover both, asserting no apply action exists in the newer case
- [x] 6.8 Reflect import stages and the outcome live, naming the safety capture on completion and on a mid-extract failure; verify a test drives the stages and asserts the capture name is shown
- [x] 6.9 Disable the apply action during any maintenance operation and name the operation in progress; verify a test asserts the disabled state and the message

## 7. Documentation and verification

- [x] 7.1 Document the import flow in the README — the archive shapes accepted, that the import is destructive, and that a backup is taken first; verify the section renders and the configuration table is unchanged
- [x] 7.2 Run `ruff format --check` and `ruff check` over the files this change touches only, per the repository's pre-existing formatting state; verify both pass for those paths
- [x] 7.3 Run the full test suite and assert no regression in the backup, restore, config, or gamerule suites; verify the run is green
- [x] 7.4 Live-verify on the test host: import the reference Crafty archive over a running server, and assert the server restarts into the imported world, the world's seed matches, the pre-import backup is listed and restorable, and the server's configured gamerules are reasserted rather than the imported world's
- [x] 7.5 Live-verify the refusal paths on the test host: an archive with no world, a zip that is not an archive, and an insufficient-space condition; assert each refuses without stopping the server
- [x] 7.6 Live-verify recovery: restore the pre-import backup taken in 7.4 and assert the original world returns intact
