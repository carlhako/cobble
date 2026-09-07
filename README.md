# cobble

A supervised web control panel for a Minecraft **Bedrock Dedicated Server** (BDS),
built for an unprivileged amd64 Debian 13 LXC on Proxmox.

Cobble is a single systemd unit. It spawns BDS as a direct child process, owns its
stdin/stdout pipes, streams the console to a browser over SSE, parses stdout into
typed events, and exposes start/stop/restart plus live status. The web interface is
compiled to static assets at build time and served by the same process — no Node
runtime in the container.

This repository is milestone **M1 (foundation)**: process supervision, event
parsing, the console, status, the HTTP interface, the web shell, and the install
path. Auto-updates, backups, configuration editing, and the player roster are later
milestones that build on what is here.

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

Open `http://<container-ip>:8000/` in a browser on the LAN.

## Filesystem layout

```
/opt/cobble/venv/         virtualenv with cobble + deps installed (bundle included)
/srv/bedrock/
    versions/<version>/   extracted BDS, one directory per version
    current -> versions/… symlink naming the active version
/var/lib/cobble/          cobble's own durable state (backed up as a unit)
/backup/                  default backup destination (M2)
```

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
