# Design

## Context

See proposal.md (Why) for the motivation. The shape of the approach is set by the installed deployment's constraints:

- `cobble.service` runs as the unprivileged `cobble` user with `NoNewPrivileges=true` and `ProtectSystem=strict`. Only `/srv/bedrock`, `/var/lib/cobble` and `/backup` are writable. `/opt/cobble` (the venv), `/etc/systemd/system` and apt are all out of reach, and there is no polkit rule allowing `systemctl`.
- An upgrade has to do more than swap the wheel. v0.4.0 changed the unit file itself (`CAP_NET_BIND_SERVICE` for port 80), and future releases may change packages. Only `install.sh`, run as root, covers all of that.
- `install.sh` is already idempotent, and it ends with an explicit `systemctl restart`. It accepts `RELEASE_TAG` and `COBBLE_TARBALL`. `release.yml` ships the whole `deploy/` directory inside `cobble.tar.gz` and attaches `install.sh` separately. GitHub records a `sha256` digest for each release asset.
- The supervisor persists `desired_running` in `runtime.json` and respawns Bedrock on cobble start. It already has an exclusive maintenance-ownership mechanism (`MaintenanceConflictError`, a status `maintenance` view with operation and step).
- `__version__` in `cobble/__init__.py` and `version` in `pyproject.toml` are maintained by hand, in parallel.
- The existing "Updates" vocabulary in the UI and API means *Bedrock server* updates.

## Goals / Non-Goals

**Goals:**
- One click from the panel upgrades cobble. This uses the same `install.sh` path as a manual upgrade, so there is only one upgrade mechanism to test.
- The privileged part is small, lives in root-owned files, takes a single validated input, and verifies what it downloads.
- An upgrade never loses the world, and it restores the server's running intent.

**Non-Goals:**
- Automatic or scheduled cobble upgrades. Upgrades are always requested by an operator.
- Downgrading from the UI, and pre-release or beta channels. Downgrade stays possible manually with `RELEASE_TAG`.
- Automatic rollback after a failed install. The design limits how much a failure can break, and recovery is a manual installer run (see Risks).
- Web authentication. The panel remains LAN-only and unauthenticated, and `auth_guard` is still the single hook for adding it.

## Decisions

### D1. The release check runs in the backend, against the GitHub REST API

A `ReleaseChecker` in cobble calls `GET https://api.github.com/repos/{repo}/releases/latest`. That endpoint already excludes drafts and pre-releases. The checker keeps the last result in memory and in `/var/lib/cobble/release_check.json`, so a restart doesn't blank the badge while it is offline. It runs about 30 s after startup, so it never delays bootstrap, and then every 12 h (`COBBLE_RELEASE_CHECK_INTERVAL`). `COBBLE_RELEASE_CHECK_ENABLED=false` turns it off for air-gapped hosts. Requests send `If-None-Match` with the cached ETag. A 304 response doesn't count against the 60/hour unauthenticated limit.

- *Alternative: check from the browser.* Rejected. Every tab would call GitHub, results would differ between tabs, and the upgrade endpoint needs the checked tag on the server side anyway.
- *Alternative: follow the `/releases/latest` HTML redirect.* Rejected. It is scraping, and it gives no release metadata or digests.

Versions are parsed as `v?MAJOR.MINOR.PATCH` into integer tuples. A string that doesn't parse means availability is unknown and never counts as an update. This avoids adding `packaging` as a dependency.

The User-Agent becomes `cobble/{__version__} (+https://github.com/carlhako/cobble)` and applies to all outbound requests, including the Bedrock vendor requests. The `__version__` drift is closed by a unit test asserting that it equals `pyproject.toml`'s version. `importlib.metadata` isn't used because it reports the wrong value when running from a source checkout.

### D2. Unprivileged request, privileged helper: a systemd `.path` + oneshot pair

```
 cobble (User=cobble)                      root
 ------------------------------            ----------------------------------------
 POST /api/cobble/upgrade
  -> maintenance "cobble_upgrade"
  -> verified backup (server left stopped)
  -> write /var/lib/cobble/upgrade/request.json   (tmp + rename)
                    |                      cobble-upgrade.path
                    +--------------------> PathExists=/var/lib/cobble/upgrade/request.json
                                              |
                                              v
                                           cobble-upgrade.service (Type=oneshot, root)
                                           /usr/local/libexec/cobble/cobble-upgrade
                                            1. consume + validate request
                                            2. GET releases/tags/<tag> (API)
                                            3. download install.sh + cobble.tar.gz
                                            4. verify sha256 == asset digest
                                            5. COBBLE_TARBALL=... RELEASE_TAG=<tag>
                                               bash install.sh
                                                 -> systemctl restart cobble
                                            6. write /var/lib/cobble-upgrade/status.json
```

This is the standard systemd way for a sandboxed service to request a privileged action. The service never holds root, and its only lever is "a file with a tag in it exists".

- *Alternative: a polkit rule letting `cobble` run `systemctl start cobble-upgrade.service`.* Rejected. It adds a polkit dependency and configuration to a minimal LXC, and it still needs a way to pass the tag.
- *Alternative: a sudoers entry.* Rejected. It conflicts with `NoNewPrivileges=true`, and sudo isn't installed on minimal Debian.
- *Alternative: in-process pip upgrade + exit.* Rejected. `/opt` is read-only under `ProtectSystem=strict`, and it would miss unit-file and package changes (see Context).

### D3. The helper treats everything from cobble as untrusted

- **Location.** The helper is a stdlib-only Python 3 script at `/usr/local/libexec/cobble/cobble-upgrade`, owned by root, mode 0755, run with the system `/usr/bin/python3`, never the venv it is replacing. It must not live under `/opt/cobble`, which is owned by `cobble`. A script the `cobble` user could edit and root would then run is privilege escalation.
- **Input.** The helper `lstat`s the request and refuses symlinks and anything that isn't a regular file of 4 KiB or less. It atomically renames the request to `request.processing` first, so the `.path` unit can't retrigger in a loop, then reads it. The only field it uses is `tag`, which must match `^v[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$`. Anything else is recorded as `rejected`.
- **Source.** The repository is fixed in the helper when `install.sh` installs it (the installer's `REPO`). The request can't choose it. The helper only fetches assets named `install.sh` and `cobble.tar.gz` from that tag's release. Downloads go to a root-owned `mktemp -d`.
- **Integrity.** Each asset's `digest` (`sha256:...`) comes from the release API and is compared with the downloaded file. The helper fails closed if the digest is missing or doesn't match.
- **Output.** Status is written only to `/var/lib/cobble-upgrade/`, a root-owned directory with mode 0755 whose `status.json` has mode 0644. Cobble can read it under `ProtectSystem=strict` but can't plant symlinks in it. Root never writes into the `cobble`-owned state directory, apart from removing its own `request.processing`, which it does after `lstat`.

### D4. Status file and the in-progress state

`/var/lib/cobble-upgrade/status.json` contains `{tag, state: running|succeeded|failed|rejected, started_at, finished_at, exit_code, log_tail}`. `log_tail` is the last ~200 lines of installer output. The full output also goes to the journal (`journalctl -u cobble-upgrade`).

When cobble requests an upgrade, it records `{from, to, requested_at}` in its own state directory (`upgrade_pending.json`), which is authoritative for `from`. The upgrade's progress is reported as follows:

- **pending**: the request file exists, or `request.processing` exists, and status isn't terminal for that tag.
- **running**: the status file says `running` for that tag.
- **succeeded / failed**: a terminal status for that tag. On startup, cobble joins its pending record with the helper status to report the outcome, then clears the pending record.

"Helper installed" means `/usr/local/libexec/cobble/cobble-upgrade` exists and `/var/lib/cobble-upgrade/` exists. Both paths are readable by the service. When they are missing, the API returns the manual command `curl -fsSL https://github.com/carlhako/cobble/releases/latest/download/install.sh | bash`.

### D5. Backup first, then hold maintenance until the process is replaced

The upgrade is a maintenance operation named `cobble_upgrade`, so it can't overlap a backup, update, restore or import. That is exactly the existing `MaintenanceConflictError` behaviour. It captures a verified backup through the same path as the pre-update backup, but **does not restart the server afterwards**. This means the only stop players see is the one for the backup, and the restart of cobble doesn't stop Bedrock a second time. `desired_running` is not modified, so the upgraded cobble respawns the server exactly when it was meant to be running.

Cobble then writes the request and stays in maintenance (step `waiting_for_helper`, then `installing`, as it polls the status file every 2 s) until it is restarted.

If the helper reports `failed` or `rejected`, or nothing progresses within 15 minutes, cobble releases maintenance and restarts the server if `desired_running`. It then reports the failure, so a failed download never leaves the server down.

- *Alternative: skip the backup.* Rejected. A new cobble may migrate `cobble.db` or other state, and the project's rule is that anything that changes the installed software backs up first (compare the `server-updates` pre-update backup).

### D6. The installer swaps the venv atomically

Today `install.sh` runs `python3 -m venv` over the live venv and pip-installs into it. A failure partway leaves a mixed venv. The installer changes to build `$PREFIX/venv.new`, install into it, then `mv venv venv.old && mv venv.new venv` and restart. It removes `venv.old` only after `systemctl restart` succeeds and `/health` answers (up to about 60 s). If the new venv doesn't come up, it swaps back and restarts the old one. This protects manual and one-click upgrades equally.

The installer also installs the helper script, the root-owned directories, and the two units. It runs `systemctl enable --now cobble-upgrade.path`.

### D7. API and UI

Routes live under `/api/cobble`, all behind `auth_guard`:

- `GET /version` returns `{current, latest, update_available, release_url, checked_at, check_error, one_click_available, manual_command, upgrade: {state, from, to, finished_at, log_tail} | null}`.
- `POST /check` re-runs the check.
- `POST /upgrade {version}` returns 409 with codes `no_update_available`, `helper_not_installed`, `upgrade_in_progress`, `maintenance_conflict`, or `version_mismatch` (when the named version is not the one currently reported). Requiring the version in the body means the operator confirms the version they were shown.

Header badge (`App.tsx`): `[0.4.0]` uses the existing success-green token. `[0.4.0 update available]` uses the warning-orange token and is an `<a target="_blank" rel="noopener">` to `release_url`. The shell fetches `/version` on load and every 5 minutes, which is enough for a 12 h cadence without touching the SSE status payload.

Settings tab card: headed "cobble (control panel)" to separate it from the Bedrock server's version panel. Release notes are a link to the GitHub release page only. The card doesn't render the release body, so the API doesn't return it. The Upgrade button opens a confirmation modal in the same style as restore.

After an upgrade is accepted, the UI shows an in-progress banner and polls `/health` every 3 s. It ignores connection errors, and when the `version` field differs from the one it loaded with, it runs `location.reload()`. `index.html` must be served with `Cache-Control: no-cache` so the reload picks up the new hashed assets. Hashed assets can keep long caching.

## Risks / Trade-offs

- **[Risk] Anyone on the LAN can trigger an upgrade.** → The same is true of stop, restore and import today. The worst case is installing an official, checksum-verified release of this repository. It can't be used to pick a version that isn't a release, or a different source.
- **[Risk] GitHub account or release compromise ships malicious code to root.** → That trust already exists with `curl | bash` at install time. The digest check protects against corrupted or tampered downloads, not a compromised publisher. Signing releases is future work.
- **[Risk] The installer fails after the venv swap and the new cobble won't start.** → D6 swaps back automatically. If even that fails, the fix is re-running the installer by hand, and `status.json` plus the journal show why.
- **[Risk] The helper is killed mid-install (container shutdown).** → On the next boot, `request.processing` exists without a terminal status. Cobble reports this as `failed` (interrupted) after the 15 minute timeout. The venv is either old or new, never mixed (D6).
- **[Trade-off] Two stops are avoided, but the server is down from the backup until the new cobble starts.** → Typically backup time plus ~1 minute. The confirmation dialog says the server will be stopped.
- **[Risk] Existing installs (v0.4.0 and earlier) have no helper.** → The card shows the manual command. One manual run installs the helper, and from then on one-click works.
- **[Risk] GitHub API rate limit behind shared NAT.** → ETag with 304, a 12 h interval, and the cached last result. A 403 or 429 is treated as unknown, not as an error.

## Migration Plan

1. Release v0.5.0 with this change. Existing deployments see `[0.4.0 update available]` only once they are running v0.5.0 or later, because v0.4.0 has no checker. So v0.4.0 users upgrade by hand once, using the manual command in the README. That run installs the helper.
2. From v0.5.0 onwards, upgrades are one-click.
3. Rollback: run `RELEASE_TAG=v0.4.0 bash install.sh` as root. The helper units stay installed but idle, and v0.4.0 ignores them.

Live verification on cobble-2 (10.0.1.165) covers four cases: a manual 0.4.0 → 0.5.0 upgrade that installs the helper; a one-click upgrade to a test tag published as a normal release in a fork or a throwaway repo via `COBBLE_REPO`; a failed checksum; and restore of the server's running state.
