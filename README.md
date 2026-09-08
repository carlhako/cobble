# cobble

A supervised web control panel for a Minecraft **Bedrock Dedicated Server** (BDS),
built for an unprivileged amd64 Debian 13 LXC on Proxmox.

Cobble is a single systemd unit. It spawns BDS as a direct child process, owns its
stdin/stdout pipes, streams the console to a browser over SSE, parses stdout into
typed events, and exposes start/stop/restart plus live status. The web interface is
compiled to static assets at build time and served by the same process — no Node
runtime in the container.

This repository covers **M1 (foundation)** — process supervision, event parsing,
the console, status, the HTTP interface, the web shell, the install path — plus
**M2** (auto-updates and backups) and **M3** (editing `server.properties` from the
browser). The player roster and gamerule editing are later milestones that build
on what is here.

## Container prerequisites

| Requirement | Value | Why |
|---|---|---|
| Architecture | **amd64 (x86-64)** | BDS ships no ARM build; cobble refuses to install elsewhere. |
| OS | Unprivileged **Debian 13** LXC (Debian 12 also works) | glibc ≥ 2.26 required by BDS; Debian 13 = 2.41. |
| Memory | ~2 GB RAM | BDS plus a small world; more for larger worlds. |
| Timezone | **Set explicitly** (`timedatectl set-timezone …`) | An unset zone places later scheduled work (M2's 04:00 update) at an unexpected hour. |
| Networking | UDP **19132** (IPv4) and **19133** (IPv6) reachable on the LAN | BDS listens on these. Bridged networking needs no port forwarding for LAN-only use. |
| Backup mount | `/backup` as a bind mount from the Proxmox host (optional, M2) | Cobble treats it as a plain path; NFS/CIFS mounting is a host concern. |
| Build tools | **None** | The release ships a pre-built wheel (frontend bundle included). The install script needs `python3`, `python3-venv`, `curl`, `unzip` and installs every dependency as a pre-built wheel — no compiler. |

## Install

On the target container, as root:

```
curl -fsSL https://github.com/carlhako/cobble/releases/latest/download/install.sh | bash
```

The script verifies architecture and glibc, installs `python3`/`curl`/`unzip`,
fetches the release tarball, creates `/srv/bedrock` and `/var/lib/cobble`, and
installs and enables `cobble.service`. On first start cobble resolves the current
BDS version, downloads and extracts it into `/srv/bedrock/versions/<version>/`, and
points `/srv/bedrock/current` at it.

A fresh install sets `allow-list=false` in `server.properties` so the server is
joinable on the LAN immediately. Turn the allowlist on from the console
(`allowlist on` after `allowlist add <gamertag>`) if you want to restrict it.

Open `http://<container-ip>:8000/` in a browser on the LAN.

## Filesystem layout

```
/opt/cobble/venv/         virtualenv with cobble + deps installed (bundle included)
/srv/bedrock/
    versions/<version>/   extracted BDS — pure vendor payload, one directory per version
    current -> versions/… symlink naming the active version (the only thing an update swaps)
    data/                 mutable state; BDS runs with this as its working directory
        server.properties   real file (operator config)
        allowlist.json      real file
        permissions.json    real file
        worlds/             real directory (LevelDB world; stable path across versions)
        bedrock_server -> ../current/bedrock_server   vendor payload, symlinked in
        definitions -> ../current/definitions         …and every other payload entry
/var/lib/cobble/          cobble's own durable state (backed up as a unit)
/backup/                  backup destination — actively used from M2 (scheduled, pre-update, on demand)
```

The world and the operator-editable config live under `/srv/bedrock/data/`, which
a version swap never touches. Each version directory holds only files supplied by
the vendor and can be removed without affecting the world. An update changes only
the `current` symlink; the `data/` payload symlinks resolve through it.

On first start against a **pre-M2 (M1) installation** — one whose world is still
inside `versions/<current>/` — cobble performs a one-time migration: it takes a
verified backup, moves `worlds/` and the config files into `data/`, lays out the
payload symlinks, and records completion. The migration is safe to interrupt and
never runs twice.

## Configuration

Settings load from environment variables prefixed `COBBLE_`, then a TOML file
(`COBBLE_CONFIG_FILE`, default `/etc/cobble/cobble.toml`), then documented defaults.
Cobble runs with no config file present.

| Setting | Default | Meaning |
|---|---|---|
| `COBBLE_BEDROCK_ROOT` | `/srv/bedrock` | Per-version installs and the `current` symlink. |
| `COBBLE_STATE_DIR` | `/var/lib/cobble` | Cobble's durable state. |
| `COBBLE_BACKUP_DIR` | `/backup` | Backup destination (plain path). |
| `COBBLE_SHUTDOWN_TIMEOUT` | `120` | Seconds to wait after `stop` before SIGKILL. |
| `COBBLE_READINESS_TIMEOUT` | `120` | Seconds to wait for the startup-complete line. |
| `COBBLE_CRASH_RESTART_THRESHOLD` | `3` | Crashes in the window after which auto-restart is abandoned. `0` disables it. |
| `COBBLE_CRASH_RESTART_WINDOW` | `300` | Sliding window in seconds for the threshold. |
| `COBBLE_PORT` | `8000` | HTTP port. |
| `COBBLE_MAINTENANCE_TIME` | `04:00` | Local `HH:MM` for the nightly window (scheduled backup, then update check — one server stop). Empty string disables all scheduled work; on-demand backup/update still work. |
| `COBBLE_BACKUP_ENABLED` | `true` | Include a backup in the nightly window. |
| `COBBLE_UPDATE_ENABLED` | `true` | Include an update check (and automatic apply) in the nightly window. |
| `COBBLE_BACKUP_RETENTION` | `7` | Backups to keep. Older ones are pruned oldest-first; the most recent usable backup is never pruned. |
| `COBBLE_UPDATE_GRACE_SECONDS` | `60` | After a new version signals readiness, seconds it must keep running before the update is called a success. An exit inside this window triggers automatic rollback. |
| `COBBLE_PLAYER_HISTORY_CHECKPOINT_SECONDS` | `300` | How often the last-known-active time of each open player session is refreshed. Bounds the playtime a session can lose if cobble is killed without closing it — that session is closed at its last checkpoint on the next start. A clean stop or an observed exit still closes sessions exactly; this only backstops power loss. |

Set the container timezone explicitly (`timedatectl set-timezone …`) — the nightly
window runs in local wall-clock time. The resolved next-run time is shown in the
web interface so a misconfigured zone is visible.

### Editing the Bedrock server configuration

The **Configuration** section of the web interface edits `server.properties`
directly. Recognised keys are shown as typed inputs — a checkbox, a bounded
number, a dropdown — with their documented default and a short description; keys
cobble does not recognise (an operator-added key, one a newer BDS introduced)
appear as plain editable text and are never dropped. `level-name` is presented as
a picker over the worlds under `data/worlds/`, with "create a new world" a
separate, explicitly confirmed action.

Saving is always safe and never disturbs a running server: **BDS reads
`server.properties` only when it starts.** After a save, cobble compares the file
on disk against a snapshot taken when the running server was last started and
reports exactly which settings differ. Applying them is a separate act — restart
now from the pending-changes panel, or defer it. A deferred change is not inert:
it takes effect at the **next start for any reason**, including an automatic crash
restart or the nightly update. The pending state is shown whenever the section is
opened, not only right after a save.

Writes change only the lines they touch — comments, blank lines, key order, and
unrecognised keys are preserved, so a hand-edited or vendor-commented file
survives a save intact. Values are validated: a wrong type (a word in a number
field, a value outside an enum) is rejected with a per-setting reason and nothing
is written; a value of the right type that is merely outside cobble's recommended
range is saved with a warning. Configuration writes are refused while an update,
backup, or restore is in progress; reads stay available.

### Players

The **Players** section lists everyone who has played on this server — online now
or not — with total playtime, session count, and when they were last seen.
Selecting a player shows their individual sessions, most recent first, each with
its start time, duration, and how it ended.

Player history is kept in a small SQLite database at `<state_dir>/cobble.db`. It
is written by a consumer of the same event stream the console uses; a write
failure is logged and dropped, never interrupting the server. A player is
identified by the stable `xuid` the server reports, so a display-name change
keeps the same history — only the shown name updates, and each session also keeps
the name as seen at the time.

Playtime is only what cobble observed. Time the server ran without cobble
watching is never credited. The Bedrock server reports no per-player disconnect
when it shuts down, so cobble closes any still-open session itself: exactly, at
the stop time, for any stop it initiates (manual, restart, nightly maintenance,
update); exactly, at the detection time, for a server that exits on its own; and,
only if cobble itself is killed without warning, approximately — the session is
closed at its last checkpoint (see `COBBLE_PLAYER_HISTORY_CHECKPOINT_SECONDS`) on
the next start. A session closed that last way is marked, and any total that
includes one is shown as approximate (`~`) rather than exact.

**History begins when recording begins.** There is no backfill source: an
installation that ran before this release has no earlier history, and the roster
shows the date from which history has been recorded so that an absence of early
data reads as "never collected", not "lost". `cobble.db` is inside the backup set
by virtue of living in `state_dir`, and a backup checkpoints it before capture so
the restored copy opens cleanly.

### Reverting to a pre-M2 (M1) cobble release

An M1 cobble release has no knowledge of `data/`, so reverting after the migration
has run needs a manual move back, with the server stopped:

```
systemctl stop cobble
cd /srv/bedrock
mv data/worlds "$(readlink current)/worlds"
mv data/server.properties data/allowlist.json data/permissions.json "$(readlink current)/"
rm -rf data
rm /var/lib/cobble/layout_migration.json
# then install the M1 release and start it
```

The pre-migration backup captured in `/backup/` also contains the world in a
restorable archive if the move cannot be done by hand.

## Development

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
npm --prefix web install

# checks
ruff check . && ruff format --check .
pytest
npm --prefix web run lint
npm --prefix web run test
npm --prefix web run build     # emits src/cobble/static/

# run locally (serves API; UI too if you ran the build)
python -m cobble
```

## License

MIT
