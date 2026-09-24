# Tasks

## 1. Release check records release notes (backend)

- [x] 1.1 Add `name`, `published_at`, `notes` to `ReleaseCheckState`, parse them from the `releases/latest` payload (blank `body` → `None`), and expose `release_name`, `published_at`, `notes` from `ReleaseChecker.view()`. Verify with new cases in `tests/selfupdate/test_release_check.py` (notes present, empty body, whitespace body).
- [x] 1.2 Persist `schema: 2` in `release_check.json`, and have `_load()` discard the ETag from a file without it (design D2). Verify with a test that a v0.5-shaped state file with an ETag leads to an unconditional request (no `If-None-Match`) and that the notes are stored afterwards.
- [x] 1.3 Confirm `/api/cobble/version`, `/check`, and `/upgrade` pass the new fields through. Verify by extending `tests/api/test_cobble_api.py` to assert `notes`, `release_name`, `published_at` in the response.

## 2. Hidden section support (frontend shell)

- [x] 2.1 Add optional `nav` to `Section` in `web/src/sections.tsx`, and render nav links only for sections without `nav: false` in `App.tsx`, while still routing every section. Verify with a shell test that a `nav: false` section is absent from the nav but renders at its path.

## 3. Cobble page

- [x] 3.1 Add `react-markdown` to `web/package.json` dependencies. Verify that `npm --prefix web ci && npm --prefix web run build` succeeds.
- [x] 3.2 Extend `CobbleVersion` in `web/src/api/client.ts` with `release_name`, `published_at`, `notes` (all nullable). Verify with `npm --prefix web run typecheck` (or the build).
- [x] 3.3 Create `web/src/sections/Cobble.tsx` and move `CobbleCard` there from `UpdatesBackups.tsx` unchanged. Register `{ path: "/cobble", nav: false }` in `sections.tsx`. Verify that the moved card tests pass when pointed at the new page.
- [x] 3.4 Add the "What's new in <version>" block: release title/version, publish date, `react-markdown` body with no raw HTML and external links opening in a new tab; "No release notes were published" when `notes` is null; nothing when `latest` is null. Add a "View on GitHub" link in place of the small "release notes" link. Verify with tests covering notes rendered, the no-notes message, the unknown-release state, and a `<script>`/`<img onerror>` body rendered as inert text.
- [x] 3.5 Remove `<CobbleCard />` from the Settings tab in `MaintenanceTabsPanel`. Verify with a test in `updates_backups.test.tsx` that the Settings tab shows no cobble upgrade controls.

## 4. Header badge

- [x] 4.1 Change `VersionBadge` in `App.tsx` to a router `Link` to `/cobble` in the current, update-available, and unknown states, keeping classes, text, and titles. Verify by updating `web/src/test/cobble_version.test.tsx`: each state is a link with `href="/cobble"`, and clicking it shows the cobble page.

## 5. Release notes publishing

- [x] 5.1 Create `CHANGELOG.md` with `## <version> - <date>` sections for 0.5.1, 0.5.0, and 0.4.0, written from git history (0.4.0 copied from its GitHub release body). Verify by review against `git log v0.4.0..v0.5.1`.
- [x] 5.2 Add `.github/scripts/release-notes.sh <version>` to print the trimmed section, and fail naming the version when it is missing or empty. Verify with a pytest in `tests/deploy/` covering present, missing, empty, and last-section cases.
- [x] 5.3 In `.github/workflows/release.yml`, run the script with the tag's version before the build, write `release-notes.md`, and pass `body_path: release-notes.md` to `action-gh-release`. Verify by running the script locally for `0.5.1` and by checking that the tarball guard test still passes (the script is not in the tarball).
- [x] 5.4 **Needs operator go-ahead (public change):** backfill the v0.5.0 and v0.5.1 GitHub release bodies from `CHANGELOG.md` with `gh release edit`. Verify with `gh release view v0.5.1 --json body`.

## 6. Docs and end-to-end check

- [x] 6.1 Update the README (where it describes upgrading cobble and the release process) so it points at the header badge / cobble page and says that each release needs a CHANGELOG entry. Verify by reading the updated sections.
- [x] 6.2 Run the full suites: `pytest` and `npm --prefix web test`, plus lint on the changed files. Verify that everything passes.
- [x] 6.3 Deploy to the test LXC, click the header badge, and confirm the page shows installed/latest versions, rendered notes, the GitHub link, and the upgrade button, and that the Settings tab no longer has the card. Verify with a screenshot of the cobble page.
