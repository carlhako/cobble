## Why

Running a Minecraft Bedrock dedicated server on a Proxmox LXC currently means SSH: start it by hand, read the console over a terminal, edit `server.properties` in `vi`, and hope nothing needs restarting while you're away. There is no supervision, no safe way to hand control to anyone else, and no foundation on which auto-updates or backups could be built.

Cobble replaces that with a single supervised service exposing a web UI. This change delivers the foundation milestone (M1): the process that owns the Bedrock server and the UI that drives it. Every later milestone — auto-updates, configuration, gamerules, player moderation — depends on the process supervision and stdout event parsing established here, so it must come first and be got right.

## What Changes

- **New Python service (`cobble`)** — FastAPI + uvicorn, running as a single systemd unit, which spawns and supervises the Bedrock Dedicated Server (BDS) as a direct child process and owns its stdin/stdout pipes for the life of the process.
- **Server lifecycle control** — start, stop, and restart BDS from the web UI. Stop issues the `stop` console command and waits for a clean save (configurable timeout, default 120s) before escalating to SIGKILL, so LevelDB is never torn by an impatient supervisor.
- **Live console** — BDS stdout is streamed to the browser over SSE, with a command input that writes to BDS stdin. This is the SSH replacement.
- **Structured event parsing** — stdout lines are parsed into typed events (server ready, player connected/disconnected/spawned, command output) rather than being treated as opaque text. Consumed by the UI now; consumed by the M4 player roster later.
- **Status and health** — current run state, resolved BDS version, uptime, online player count, derived from parsed events rather than polled from the filesystem.
- **React web UI** — React + Vite + TypeScript, compiled to static assets at build time and served by the FastAPI process. No Node runtime in the container.
- **Installation for Proxmox LXC** — a systemd unit and an install script targeting an unprivileged amd64 Debian 13 container, plus a GitHub Actions workflow producing a release tarball with the frontend pre-built.
- **First-run bootstrap** — if no BDS installation is present, fetch the current version and lay out the versioned directory structure that M2's update mechanism will later swap between.

Not breaking: this is a greenfield project with no existing consumers.

## Capabilities

### New Capabilities

- `server-lifecycle`: Supervision of the BDS child process — start, stop, restart, clean-shutdown guarantees, crash detection and restart policy, and the run-state model the rest of the system observes.
- `server-console`: Bidirectional console access — streaming BDS stdout to clients, accepting commands into BDS stdin, and the single-writer guarantees that make that safe.
- `server-events`: Parsing BDS stdout into structured, typed events, and the contract those events present to consumers. Establishes the event vocabulary M4 depends on.
- `server-status`: Observable state of the managed server — run state, installed version, uptime, online players — and how it is derived and exposed.
- `installation`: Filesystem layout, BDS acquisition and first-run bootstrap, systemd unit definition, and the LXC install path. Establishes the versioned directory structure and the `/var/lib/cobble/` state directory that M2 backups will snapshot.
- `web-ui-shell`: The frontend application shell — routing, layout, live-connection handling and reconnection, and the visual foundation later screens are built into.

### Modified Capabilities

None. This is the first change in the project; no specs exist yet.

## Impact

**New code** — a Python package (FastAPI app, BDS supervisor, stdout parser, SSE transport) and a React/Vite/TypeScript frontend, in one repository.

**Runtime dependencies** — Python 3.11+ (Debian 13 ships 3.13), FastAPI, uvicorn. Node and npm are build-time only and never installed in the container.

**External dependencies** — the Bedrock Dedicated Server binary itself, and Mojang's download-links API (`net-secondary.web.minecraft-services.net`) for acquisition. Downloads require a User-Agent header; requests without one fail.

**Platform constraints** — BDS is amd64-only and requires glibc ≥ 2.26. It statically links libstdc++ and needs no OpenSSL. Any modern amd64 Debian/Ubuntu LXC satisfies this; ARM hosts cannot run this software at all.

**Deployment** — one systemd unit (`cobble.service`) with BDS as its child. Restarting cobble therefore restarts the game server; this is an accepted trade-off for v1, documented in design.md along with the migration path away from it.

**Security posture** — LAN-only with no authentication in v1. The design constrains all state-changing operations behind a single API surface so authentication can be added later as an insertion rather than a rewrite. Explicitly out of scope here, not designed away.

**Deferred to later milestones** — auto-updates and backups (M2), `server.properties` and gamerule editing (M3), player roster and moderation (M4). This change establishes the process supervision, event parsing, and directory layout that all three build on, but implements none of them.
