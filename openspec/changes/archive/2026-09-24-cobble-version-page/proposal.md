# Proposal

## Why

Upgrading cobble is hard to find. The orange `[x.y.z update available]` header badge sends the operator off to GitHub, and the one-click upgrade button sits four clicks deep: Updates & Backups, then the maintenance panel's Settings tab, which is not the default tab. The spec calls this a "settings screen" that does not exist. The operator also cannot read what a release changes without leaving cobble. The two most recent releases (v0.5.0, v0.5.1) were published with empty notes anyway, because the release workflow never sets them.

## What Changes

- A new **cobble page** at `/cobble`, reached from the header badge and not listed in the navigation bar. It shows the installed version, the latest known release, the update status, when the release check last ran with a check-now action, the latest release's notes rendered as Markdown, a link to the release on GitHub, the upgrade action with its existing confirmation, the manual root command when one-click upgrade is not possible, and the most recent upgrade's outcome.
- The header version badge **always** links to the cobble page, whether cobble is current, out of date, or availability is unknown. Its colours and text are unchanged. **BREAKING** (UI behaviour): it no longer opens GitHub directly.
- The cobble upgrade card is **removed** from the Updates & Backups Settings tab. That tab keeps only the maintenance settings.
- The release check also records the latest release's **notes, title, and publish date** from the response it already fetches, and reports them through the programmatic interface. Only the latest release's notes are kept. Notes for skipped intermediate releases are out of scope.
- Release publishing: a **`CHANGELOG.md`** becomes the source of release notes. The release workflow publishes the tag's section as the GitHub release body and **refuses to publish** a tag that has no changelog section. Entries are written for the releases already published.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `cobble-self-update`: the release check records and reports the latest release's notes, title, and publish date. A new requirement says every published release carries release notes taken from the changelog.
- `web-ui-shell`: the header badge links to the cobble page instead of GitHub. The "Cobble upgrades are available from the settings screen" requirement becomes a cobble page requirement, and the page adds rendered release notes and a GitHub link. The shell supports a section that is routable but not listed in the navigation bar.

## Impact

- **Backend**: `src/cobble/selfupdate/release_check.py` (state, persistence, view), `src/cobble/api/cobble.py` (response passes the new fields through), plus tests in `tests/selfupdate/` and `tests/api/test_cobble_api.py`.
- **Frontend**: `web/src/App.tsx` (badge becomes an in-app link), `web/src/sections.tsx` (hidden `/cobble` route), a new `web/src/sections/Cobble.tsx` (the card moves here from `UpdatesBackups.tsx`), `web/src/api/client.ts` (the `CobbleVersion` type), and tests in `web/src/test/`.
- **Dependency**: `react-markdown`, a runtime dependency compiled into the bundle. The host still needs no JavaScript toolchain.
- **Release process**: new `CHANGELOG.md` and changes to `.github/workflows/release.yml`. Every future release needs a changelog entry, or the tag fails to publish.
- **API**: `GET /api/cobble/version` (and the `check`/`upgrade` responses) gain `notes`, `release_name`, and `published_at`. The change only adds fields.
