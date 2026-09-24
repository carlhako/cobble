# Changelog

Each released version has a section headed `## <version> - <date>`. The release
workflow publishes that section as the GitHub release notes, which cobble shows
on its own page before you upgrade. A tag without a section here is not
published, so add the entry with the version bump.

## 0.6.0 - 2026-09-24

### What's new

- **cobble has its own page, opened from the version in the header.** Click
  the version beside the cobble name (green when current, orange when a newer
  release is out) to see the installed and latest versions, when cobble last
  checked with a **Check now** button, and what's new in the latest release,
  before you upgrade. The **Upgrade** button and its confirmation are on the
  same page, with a link to the release on GitHub.
- The cobble upgrade controls have moved there from **Updates & Backups →
  Settings**, which now holds only the maintenance settings.
- Every release now ships with release notes, and cobble shows them in the
  panel.

### Upgrading from 0.5.x

On 0.5.x, upgrade from **Updates & Backups → Settings** as before. The orange
badge there still opens GitHub. From 0.6.0 on, the badge opens the new page.

## 0.5.1 - 2026-09-24

### Fixes

- **Servers updated to Bedrock 1.26.51.1 or later are reachable again.** That
  Bedrock version switched its network transport from RakNet to NetherNet, the
  only transport current clients support. Installs first set up on an older
  version kept `transport=raknet` through the auto-update and stopped showing
  up for players. A Bedrock update now moves any setting still at the old
  version's default to the new version's. Settings you changed are left alone,
  and version history lists what moved.
- The Dashboard shows the transport in use. When it isn't the running
  version's default, a notice says players may not be able to see or join the
  server and offers a one-click switch and restart. The Configuration page
  shows the same notice, which fixes installs that have already updated.
- The README's networking requirements now match NetherNet: TCP 19132, UDP 7551
  for LAN discovery, and per-player UDP from the ephemeral port range.

## 0.5.0 - 2026-09-24

### What's new

- **cobble can upgrade itself from the web interface.** The header shows the
  running cobble version, orange when a newer release exists, and a cobble card
  offers a one-click upgrade. cobble stops the server, takes a verified backup,
  and hands the upgrade to a root-owned helper. The helper checks the release
  against GitHub's published sha256 digests before installing it. The page
  reloads itself onto the new version, and the server comes back if it was
  running.
- **The installer upgrades in place.** It builds the new version beside the old
  one, swaps it in, and rolls back if the new cobble does not come up.

### Upgrading from 0.4.0

Installs from before 0.5.0 have no upgrade helper yet. Run the installer once
as root (the cobble card shows the command). Later upgrades can then be done
from the web interface.

## 0.4.0 - 2026-09-23

### What's new

- **Backup and version history**: new tabs list every backup ever captured
  (including ones since pruned by retention) and every successful update, with
  its trigger.
- **Live-editable maintenance settings**: a new Settings tab covers backup
  retention, turning scheduled backups on or off, and separate
  daily/weekly/monthly schedules for backups and update checks. Changes apply
  without a restart. When both schedules come due together they share one
  window, so the server stops only once.
- **Import an external world archive** into the server.
- **The control panel now serves on port 80** by default (`COBBLE_PORT`). The
  systemd unit grants `CAP_NET_BIND_SERVICE` so cobble still runs unprivileged.

### Fixes

- A schedule whose time fell while the other schedule was running is no longer
  skipped.
