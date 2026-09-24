# Proposal

## Why

Nothing in the interface shows operators which version of cobble they are running or whether a newer one exists. Upgrading means knowing to re-run the installer as root inside the container. Cobble now ships regular releases on GitHub (v0.1.0 through v0.4.0), so operators fall behind silently. A visible version, an update notice, and a one-click upgrade keep deployments current without a shell session.

## What Changes

- The header shows the running cobble version beside the brand as `[0.4.0]` in green. When a newer release exists, it turns orange, reads `[0.4.0 update available]`, and links to that release on GitHub.
- Cobble periodically checks the latest stable GitHub release of `carlhako/cobble`, caches the result, and exposes it through the programmatic interface. When the check cannot reach GitHub, the result is simply unknown and nothing is shown as an error in the header.
- The Settings tab (Updates & Backups) gains a "cobble" card. It shows the installed and latest versions, when the last check ran, a release-notes link, a "Check now" action, an "Upgrade" action, and the outcome of the last upgrade.
- One-click upgrade: cobble captures a verified backup and then records an upgrade request for the exact release tag it found. A privileged, root-owned systemd helper, which the installer sets up, acts on that request. The helper validates the tag, downloads that release's installer and tarball, verifies their published checksums, and runs the installer in place. The installer restarts cobble. Cobble itself never gains privileges.
- On older installs that lack the helper, the card shows the one-line root command to upgrade manually instead of the button.
- The installer installs and enables the upgrade helper units, so every later release is upgradable from the interface.
- The outbound client identifier is derived from the running version and the real project URL, replacing the stale hard-coded `cobble/0.1`.

## Capabilities

### New Capabilities
- `cobble-self-update`: determining whether a newer cobble release exists, and requesting, performing and reporting an in-place upgrade of cobble through a privileged helper that cobble can only ask to act.

### Modified Capabilities
- `installation`: the installer can be re-run as an in-place upgrade, and it installs the privileged upgrade helper.
- `web-ui-shell`: the header presents the cobble version and its update state, and the interface offers the upgrade action and shows its outcome.

## Impact

- **Backend**: a new release-check and upgrade-request module plus API routes under `/api`, using the `auth_guard` dependency like every other route. It is wired into `Runtime` startup and a periodic timer, and the upgrade is refused while another maintenance operation is running. `settings.py` gets the user-agent default change and new settings for the repository and check interval.
- **Deploy**: new files `deploy/cobble-upgrade.path`, `deploy/cobble-upgrade.service` and a root helper script. `install.sh` installs and enables them. The release tarball must include them.
- **Frontend**: `App.tsx` header badge, a new "cobble" card in the Settings tab of `UpdatesBackups.tsx`, API client additions, and reloading the page once it reconnects to a new version.
- **External**: an unauthenticated GitHub REST API call roughly twice a day, well inside the 60 requests/hour limit. The root helper downloads from GitHub release assets only.
- **Operational**: an upgrade restarts cobble, which cleanly stops the Bedrock server and disconnects players. The server comes back if it was running. Installs from v0.4.0 and earlier need one manual installer run before the button appears.
