# Design

## Context

- `ReleaseChecker` (`src/cobble/selfupdate/release_check.py`) calls `GET /repos/{repo}/releases/latest` and keeps only `tag_name` and `html_url`. The response also carries `name`, `published_at`, and `body` (Markdown), which are discarded. State persists to `<state_dir>/release_check.json`, and later checks send `If-None-Match` with the stored ETag.
- `/api/cobble/version` combines `release_check.view()` with the upgrade view. `check` and `upgrade` return the same shape.
- The upgrade UI is `CobbleCard` in `web/src/sections/UpdatesBackups.tsx`, rendered only inside the maintenance panel's Settings tab. The header `VersionBadge` in `App.tsx` is an `<a href={release_url}>` when an update exists and a plain `<span>` otherwise.
- `web/src/sections.tsx` is the single list that drives both nav links and routes.
- `.github/workflows/release.yml` publishes with `softprops/action-gh-release@v2`, passing only `files:`. That is why v0.5.0 and v0.5.1 have empty bodies.

## Goals / Non-Goals

**Goals:**
- One obvious place to read what's new and upgrade, one click from any screen.
- Release notes that exist for every future release, enforced by the pipeline.

**Non-Goals:**
- Notes for intermediate releases the operator would skip. Only the latest release is shown (operator decision).
- Changing the upgrade mechanics, the confirmation wording, or the helper.
- Showing notes for the *running* version when it differs from the latest (for example, a dev build).

## Decisions

### D1. Extend the existing `releases/latest` check; no extra request
Add `name`, `published_at`, and `notes` to `ReleaseCheckState` and to `view()` (exposed as `release_name`, `published_at`, `notes`). An empty or whitespace-only `body` is stored as `None`. *Alternative:* a separate endpoint that fetches notes on demand when the page opens. Rejected: it adds a per-viewer GitHub call, which the "shared, bounded" requirement forbids, and a second failure mode.

### D2. Bypass the ETag once for pre-notes cached state
A `release_check.json` written by v0.5.x holds an ETag but no notes. A conditional request would get `304`, and notes would stay missing until the next release. Add `schema: 2` to the persisted state. `_load()` treats a file without `schema >= 2` as having no ETag, so the first check after upgrade fetches the release in full. *Alternative:* always drop the ETag when `notes is None`. Rejected: a release that genuinely has no notes would then never benefit from 304s.

### D3. Hidden section flag in `sections.tsx`
Add `nav?: boolean` (default `true`) to `Section`. `App.tsx` renders routes for every section and nav links only for `nav !== false`. The cobble page is `{ path: "/cobble", label: "cobble", nav: false, element: <Cobble /> }`. *Alternative:* a one-off `<Route>` in `App.tsx`. Rejected: it breaks the "one entry in sections.tsx" pattern the shell spec describes.

### D4. Move `CobbleCard` wholesale into `sections/Cobble.tsx`
The card's logic (check, confirm, upgrade, manual command, last outcome) moves unchanged. The page adds a "What's new in <version>" block and a "View on GitHub" link, replacing the small "release notes" link. `MaintenanceTabsPanel`'s Settings tab renders only `<SettingsTab />`. Existing card tests move with it.

### D5. Badge is a router `<Link to="/cobble">` in all states
It keeps its classes and titles, so colour and text are unchanged. Before the first version response it still renders nothing, as today, so the badge never shows a version it hasn't confirmed.

### D6. Markdown via `react-markdown` with safe defaults
Use `react-markdown` with no `rehype-raw`, so raw HTML in the notes is escaped rather than rendered. Its default `urlTransform` already strips `javascript:` and other unsafe URLs. Override the `a` component to add `target="_blank" rel="noopener noreferrer"`. Images are left to the default renderer, which only loads from http(s) URLs. The notes come from our own repo, so the aim is defence in depth, not a hostile-input model. *Alternatives:* `marked` plus `dangerouslySetInnerHTML` (needs a sanitizer, easy to get wrong) or a hand-written subset renderer (more code to maintain).

### D7. `CHANGELOG.md` sections keyed by bare version; workflow extracts with a checked script
Format: `## 0.5.2 - 2026-09-25`, followed by free Markdown, and so on for each release. The extraction script is a build-time tool and must not ship in the release tarball (which copies `deploy/`), so it lives at `.github/scripts/release-notes.sh <version>`, which prints the section body (the text between that heading and the next `## `), trims it, and exits non-zero with `no CHANGELOG.md entry for <version>` when the section is missing or empty. The workflow runs it with the tag minus the `v`, writes `release-notes.md`, and passes `body_path: release-notes.md` to `action-gh-release`. It runs before the build, so a missing entry fails fast. *Alternatives:* `generate_release_notes: true` (commits land directly on main, so this yields little more than a compare link); annotated tag messages (easy to forget, can't be reviewed or edited in a PR).

### D8. Backfill
Write CHANGELOG sections for 0.5.1, 0.5.0, and 0.4.0 (copying 0.4.0's existing GitHub body) from git history. Updating the already-published v0.5.0 and v0.5.1 GitHub release bodies to match is a manual `gh release edit` step. It is listed as a task and needs the operator's go-ahead, because it changes public content.

## Risks / Trade-offs

- [A release is tagged without a changelog entry and fails to publish] → Intended. The failure message names the version. Fix: add the entry, delete the tag, re-push it.
- [Existing installs keep showing "no notes" until they check again] → D2 forces a full fetch on the first check after upgrading to this version. "Check now" works immediately.
- [`react-markdown` adds bundle weight (~40 kB min+gz with its unified deps)] → Acceptable for an admin panel served on the LAN. It loads with the main bundle, since the app does no code splitting today.
- [Operators with a bookmark or habit of the Settings tab no longer find the upgrade card there] → The header badge is visible on every screen, and the README screenshot/docs are updated.
- [Badge no longer opens GitHub directly] → The cobble page links to GitHub, one extra click for anyone who wanted GitHub.

## Migration Plan

No data migration. The persisted `release_check.json` is read forward-compatibly: unknown fields are ignored and missing ones default. D2 handles the stale ETag. Rolling back to a previous cobble ignores the new fields.
