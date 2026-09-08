## 1. Backup download route

- [x] 1.1 Add `GET /backups/{archive}` to `src/cobble/api/backups.py` that resolves the archive via `runtime.backup.store.get(archive)`, returns 404 when it is `None`, and otherwise returns a `FileResponse` for the archive file with `media_type="application/gzip"`, `filename=<archive name>`, and a `Content-Disposition: attachment` header. Guard with `auth_guard`. Verify with a new API test: capture a backup, `GET` its archive, assert 200, the `attachment` disposition, and that the body bytes equal the file on disk.
- [x] 1.2 Add tests for rejection paths in the same test module: an unknown name returns 404, and a name containing path separators or `..` returns 404 without reading any file outside the backup directory.
- [x] 1.3 Add a test that a backup recorded as not restorable (corrupt archive, manifest intact) is still downloadable — `GET` returns 200.

## 2. Backup download control in the interface

- [x] 2.1 Add a `backupsDownloadUrl(archive: string): string` helper to `web/src/api/client.ts` that returns the same base URL the other calls use plus `/backups/<encoded archive>`. Verify by importing it in the section and confirming the built URL in the browser network panel.
- [x] 2.2 In `web/src/sections/UpdatesBackups.tsx`, add a "Download" link (an `<a>` with `href={backupsDownloadUrl(b.archive)}` and the `download` attribute) to every row of the backup list, next to the Restore cell, shown for restorable and not-restorable rows alike. Verify manually against a live server: the link downloads `cobble-backup-*.tar.gz` and the file opens as a tar archive.

## 3. Shared filter bar

- [x] 3.1 Add a `FilterBar` component (new file under `web/src/sections/`, e.g. `FilterBar.tsx`) taking `value`, `onChange`, `shown`, and `total`, rendering a labelled `<input type="search">` and an `aria-live` count ("N of M shown"). Verify with the existing `web` lint/build (`npm run build` in `web/`) succeeding.
- [x] 3.2 Add a `matchesFilter(query, ...fields)` helper (whitespace-split, case-insensitive, all terms must match some field) next to `FilterBar`, and a unit test covering multi-term match, no-match, and empty-query-matches-all.

## 4. Filter on Configuration

- [x] 4.1 In `web/src/sections/Configuration.tsx`, add filter `useState` and render `FilterBar` above the settings panel. Filter `read.settings` (including the `level-name` row) with `matchesFilter` over key and `schema.description`. Keep `PendingPanel`, the maintenance banner, notes, and the "Saved." strip outside the filter. Show a "nothing matches" message inside the panel when the filtered list is empty and the query is non-empty.
- [ ] 4.2 Verify manually against a live server: typing narrows the list as you type, clearing restores it, a pending-change banner stays visible while a filter is applied, and an unmatched query shows the message with the typed text retained.

## 5. Filter on Gamerules

- [x] 5.1 In `web/src/sections/Gamerules.tsx`, add filter `useState` and render `FilterBar` above the active-world rule panel. Filter `view.rules` with `matchesFilter` over `name` and `description`. Do not filter `DefaultsEditor`. Keep the report panel, liveness/queued banners, and maintenance banner outside the filter. Show a "nothing matches" message inside the rule panel when the filtered list is empty and the query is non-empty.
- [ ] 5.2 Verify manually against a live server: typing narrows the rule list, clearing restores it, the preferred-defaults editor is unaffected, and a gamerule report banner stays visible while a filter is applied.

## 6. Spec sync and full verification

- [x] 6.1 Run `openspec validate panel-filtering-and-backup-download --strict` and confirm it passes.
- [x] 6.2 Run the Python test suite (`pytest`) and the `web` build/lint, and confirm both pass with the new tests included.
- [ ] 6.3 On the live verification host, capture a backup, download it, restore it, and confirm the player history/roster and gamerule records are intact after the restore.
