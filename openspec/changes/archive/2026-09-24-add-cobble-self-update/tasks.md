# Tasks

## 1. Version plumbing

- [x] 1.1 Change the `user_agent` default in `settings.py` to `cobble/{__version__} (+https://github.com/carlhako/cobble)`. Verify with a test asserting the header sent to the vendor source contains the running version.
- [x] 1.2 Add a test asserting `cobble.__version__` equals `pyproject.toml`'s `[project].version`. Verify it passes now and fails when either value is edited alone.
- [x] 1.3 Add settings `release_repo` (default `carlhako/cobble`), `release_check_enabled` (default true), `release_check_interval_hours` (default 12), and helper paths (`/usr/local/libexec/cobble/cobble-upgrade`, `/var/lib/cobble-upgrade`). Verify settings tests cover the defaults and env overrides.

## 2. Release checker (backend)

- [x] 2.1 Implement `vX.Y.Z` parsing and comparison. Verify unit tests cover newer, equal, older (dev build), a leading `v`, and unparseable input returning unknown.
- [x] 2.2 Implement `ReleaseChecker`: call `releases/latest` with ETag/`If-None-Match`, cache in memory and in `release_check.json`, keep the last good result on failure, and treat 403/429/network errors as unknown with `check_error`. Verify with tests using an httpx mock transport for 200, 304, 404, 403 and timeout, plus a restart that reloads the cached file.
- [x] 2.3 Schedule the checker in `Runtime.startup` (first run about 30 s after start, then on the interval) without blocking bootstrap, honour `release_check_enabled`, and cancel it on shutdown. Verify with a test that startup completes while the check is pending and that disabling it makes no request.

## 3. Upgrade request (backend)

- [x] 3.1 Implement helper detection and the manual command. Verify tests with tmp paths for present and absent helpers.
- [x] 3.2 Implement the `cobble_upgrade` maintenance operation. It takes the maintenance lock, captures a verified backup through the pre-update backup path, leaves the server stopped with `desired_running` unchanged, records `upgrade_pending.json {from,to,requested_at}`, and atomically writes `upgrade/request.json {tag}`. Verify tests show the backup happens before the request file, a backup failure writes no request, and `desired_running` is untouched.
- [x] 3.3 Implement refusals: `no_update_available`, `version_mismatch`, `helper_not_installed`, `upgrade_in_progress`, `maintenance_conflict`. Verify with one test per 409 code.
- [x] 3.4 Implement status polling during the operation (step `waiting_for_helper` then `installing`), and on `failed`/`rejected`/15 minute timeout release maintenance and restart the server if `desired_running`. Verify tests with a fake status file for each terminal state and the timeout.
- [x] 3.5 On startup, join `upgrade_pending.json` with the helper `status.json` to produce the last-upgrade outcome, then clear the pending record, treating an orphaned `request.processing` with no terminal status as interrupted. Verify tests for succeeded, failed and interrupted.

## 4. API

- [x] 4.1 Add `build_cobble_router` under `/api/cobble` with `GET /version`, `POST /check`, and `POST /upgrade {version}`, all behind `auth_guard`, registered in `Runtime.attach`. Verify API tests assert the response shape from design D7 and the 409 codes.
- [x] 4.2 Serve `index.html` (including the SPA fallback) with `Cache-Control: no-cache`. Verify with a test in `test_static_serving.py`.

## 5. Privileged helper and units (deploy)

- [x] 5.1 Write `deploy/cobble-upgrade` as a stdlib-only Python 3 script. It `lstat`s and size-checks the request, renames it to `request.processing`, validates the tag regex, uses the repo baked in at install time, fetches release metadata by tag, downloads `install.sh` and `cobble.tar.gz` to a root `mktemp -d`, verifies `sha256` against the asset `digest` (failing closed), runs `COBBLE_TARBALL=... RELEASE_TAG=... bash install.sh`, writes `status.json` with the log tail, and removes `request.processing`. Verify with pytest against the script covering a malformed tag, a symlinked request, an oversize request, a missing digest, a mismatched digest, and a success path using a fake release server and a stub installer.
- [x] 5.2 Add `deploy/cobble-upgrade.path` (`PathExists=/var/lib/cobble/upgrade/request.json`) and `deploy/cobble-upgrade.service` (`Type=oneshot`, root, runs the helper with `/usr/bin/python3`, `TimeoutStartSec` of about 20 minutes). Verify with `systemd-analyze verify` on both units.
- [x] 5.3 Extend `tests/deploy/test_release_tarball.py` to assert the tarball contains the helper and both units. Verify the test passes against a locally built tarball.

## 6. Installer

- [x] 6.1 Build the venv as `venv.new`, swap it in, restart, wait for `/health` (about 60 s), and remove `venv.old` on success or swap back and restart on failure. Verify on cobble-2 by forcing a broken wheel and confirming the old cobble keeps serving.
- [x] 6.2 Install the helper to `/usr/local/libexec/cobble/` (root, 0755) with `REPO` baked in, create `/var/lib/cobble/upgrade` (owned by cobble) and `/var/lib/cobble-upgrade` (root, 0755), install both units, and run `systemctl enable --now cobble-upgrade.path`. Verify with `systemctl is-active cobble-upgrade.path` on cobble-2 and by checking file ownership and modes.
- [x] 6.3 Update the installer header comment and README with the upgrade story: one-click from Settings, and the manual command for v0.4.0 and earlier. Verify the README renders and the command works when copy-pasted.

## 7. Web interface

- [x] 7.1 Add API client types and calls for `/api/cobble/version`, `/check` and `/upgrade`. Verify with typecheck (`npm --prefix web run build`).
- [x] 7.2 Add the header badge in `App.tsx`: green `[x.y.z]`, orange linked `[x.y.z update available]`, plain when unknown, fetched on load and every 5 minutes. Verify with `shell.test.tsx` cases for all three states and the link target.
- [x] 7.3 Add the "cobble (control panel)" card to the Settings tab showing installed and latest versions, checked-at, release notes link, Check now, the last-upgrade outcome with log tail, and either the Upgrade button (with a confirmation modal that states the server stops and players disconnect, disabled during maintenance) or the manual command with a copy button. Verify with `updates_backups.test.tsx` cases for each branch.
- [x] 7.4 Add upgrade follow-through: an in-progress banner, polling `/health` while ignoring connection errors, and `location.reload()` when the version changes. Verify with a test using fake timers that simulates a disconnect, then a new version, and asserts reload.

## 8. Verification

- [x] 8.1 Run the full backend and frontend test suites and `ruff check`, plus `ruff format --check` on changed files only. Verify all pass.
- [x] 8.2 Live on cobble-2: manually upgrade 0.4.0 to this build and confirm the helper is installed and the badge shows. Then trigger a one-click upgrade to a test release (via `COBBLE_REPO` pointing at a test repo) and confirm the backup was captured, the server stopped once and came back running, the UI reloaded onto the new version, and the outcome is shown. Also confirm a tampered asset produces `failed` with the server restored. Record the results in `live-verification.md` in this change.
