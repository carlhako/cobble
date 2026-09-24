# Live verification — cobble-2 (10.0.1.165), 2026-09-24

The test builds were throwaway tarballs made from this branch, with only the
version string changed (`0.5.0`, `0.5.1`, a deliberately broken `0.5.9`). The
one-click path ran against a local fake GitHub releases API on cobble-2
(`127.0.0.1:8765`). cobble reached it through `COBBLE_RELEASE_API_URL` in
`/etc/cobble/cobble.env`, and the helper through an `Environment=` drop-in on
`cobble-upgrade.service`. Nothing was published to GitHub. All overrides were
removed afterwards, and the host was reinstalled with this branch at its real
version (`0.4.0`).

## Manual upgrade of a v0.4.0 install (tasks 6.2, installation spec)

Starting point: cobble v0.4.0 from the published release, no helper, Bedrock running.

`COBBLE_TARBALL=cobble-0.5.0.tar.gz bash install.sh` as root:

- Exited 0, and `/health` reported `0.5.0`.
- `/usr/local/libexec/cobble` and `/usr/local/libexec/cobble/cobble-upgrade`: `root:root 755`.
- `/var/lib/cobble-upgrade`: `root:root 755`. `/var/lib/cobble/upgrade`: `cobble:cobble 755`.
- `cobble-upgrade.path` was enabled and active, and the helper's `REPO` line was baked in.
- `venv.old` was removed, and the venv's scripts point at `/opt/cobble/venv` (the shebangs were re-pointed).
- The Bedrock server was running again afterwards. `/api/cobble/version` reported `one_click_available: true`.

## One-click upgrade 0.5.0 → 0.5.1 through the web UI (task 8.2)

- The header showed an orange `[0.5.0 update available]` linking to the release page.
- Settings → cobble card: installed 0.5.0, latest 0.5.1, "Upgrade to 0.5.1". The confirmation
  stated that the server stops and players disconnect.
- The cobble journal showed one server stop (23:28:03), then `pre-upgrade` backup complete
  (23:28:06), then the request written and the step changing to "waiting for the upgrade
  helper" and then "installing cobble v0.5.1".
- Helper journal: digests of both assets verified, then the installer ran, then
  `cobble v0.5.1 installed`, and the helper's status was `succeeded`.
- cobble restarted (23:28:27) and restored the previously running server (23:28:28).
  Bedrock was down for about 25 seconds in total. `desired_running` stayed `true`.
- The browser page reloaded by itself. The header then showed a green `[0.5.1]`, and the card
  showed "Last upgrade: 0.5.0 → 0.5.1, succeeded".

## Tampered release (task 8.2)

The fake API published a wrong sha256 for `cobble.tar.gz` of `v0.5.2`. The upgrade was
requested through `POST /api/cobble/upgrade`.

- Within about 2 seconds, `upgrade.state: failed`, with the error "cobble.tar.gz does not
  match its published sha256 digest".
- Nothing was installed (`/health` still reported `0.5.1`). Maintenance was released and the
  server restarted (`run_state: running`, `desired_running: true`). The request directory was
  empty.

## Installer rollback (task 6.1)

`COBBLE_TARBALL=cobble-0.5.9.tar.gz bash install.sh`. The 0.5.9 build's `cobble.__main__`
exits immediately.

- The installer printed "cobble 0.5.9 did not start; restoring the previous version", then
  "upgrade to cobble 0.5.9 failed; the previous version is running again", and exited 1.
- `/health` then reported `0.5.1`, the Bedrock server was running, and one-click was still
  available.

## Real release check

After cleanup, the reinstalled 0.4.0 build's first check reached `api.github.com` about 30
seconds after start. It reported `latest: 0.4.0` and `update_available: false`, so the badge
is green.

## Observation

When cobble is stopped with browser tabs open, uvicorn waits its 10-second graceful-shutdown
drain for the open SSE streams ("timeout graceful shutdown exceeded") before the runtime
shuts down. This behaviour is not new. It adds about 10 seconds to any cobble restart,
including an upgrade, while a panel is open.

## Re-verification after code review fixes (later on 2026-09-24)

This run used the same fake-release setup, with throwaway builds stamped `0.5.0`, `0.5.1` and `0.5.2`.

- **Installer, 0.4.0 → 0.5.0**: a previously cobble-owned `/opt/cobble` became `root:root`
  throughout. The new venv was built there and swapped in, and Bedrock came back.
- **Retry after a failed attempt**: the first 0.5.0 → 0.5.1 request met a wrong published
  digest. The helper failed before running anything, cobble recorded `failed`, and Bedrock was
  restored. That attempt's `status.json` (tag `v0.5.1`, `failed`) was left in place, and the
  request was retried with the correct digest. cobble ignored the stale status because its
  request id did not match, and followed the new request to `succeeded`. cobble was down from
  about t+10s to t+20s.
- **Web UI, 0.5.1 → 0.5.2**: confirmation, "Backing up…", then "Upgrading". The page
  reloaded by itself onto a green `[0.5.2]`, and the outcome read `succeeded`.
- **Found and fixed while watching**: the log tail kept the installer's ANSI colour codes, and
  the view briefly read `pending` between the helper's final write and cobble's next poll.

The overrides were removed afterwards. cobble-2 was left on the `0.5.2` test build.
