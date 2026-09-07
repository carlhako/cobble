## Context

See proposal.md — Why. This section records only the external constraints that shape the architecture, several of which were verified directly against BDS 1.26.45.1 rather than taken from documentation.

**BDS has no RCON.** Control is literally writing to the process's stdin (`stop`, `list`, `allowlist reload`, `say`) and reading its stdout. There is no network control protocol. This single fact drives the process topology: exactly one process must own that pipe, for the lifetime of the server, and it must be a singleton.

**BDS keeps no player database.** `allowlist.json` and `permissions.json` ship empty and only record what an operator puts there. The only trace of who has played is three stdout lines:

```
Player connected: %s, xuid: %s
Player disconnected: %s, xuid: %s, pfid: %s
Player Spawned: %s xuid: %s, pfid: %s
```

Any player history is therefore state cobble creates and owns, derived from a stream that is only observed while cobble is running. This change does not build the roster (M4 does), but it must parse and expose these events, because history not captured is history lost forever — there is no backfill source.

**Platform limits**, verified against the shipped binary:

| Property | Value |
|---|---|
| Architecture | x86-64 only — no ARM build exists |
| glibc | ≥ 2.26 (Debian 12 = 2.36, Debian 13 = 2.41) |
| libstdc++ | statically linked — no runtime dependency |
| OpenSSL | not required |
| Other deps | pthread, dl, m, gcc_s, c, rt — all base system |

The historical "install libssl1.1" workaround no longer applies.

**Acquisition.** Mojang exposes a JSON endpoint listing current download URLs:

```
GET https://net-secondary.web.minecraft-services.net/api/v1.0/download/links
  -> result.links[] with downloadType "serverBedrockLinux"
```

No HTML scraping is needed. The zip is ~99 MB. Requests without a `User-Agent` header fail — a plain `curl -I` returns nothing, while the same request with a browser UA returns 200. This is a required header, not an optimisation.

**Deployment target.** Unprivileged amd64 Debian 13 LXC on Proxmox, intended for eventual packaging as a Proxmox helper script. This biases every decision toward fewer moving parts at install time.

## Goals / Non-Goals

**Goals:**

- One supervised process that owns BDS and survives reboot.
- Never corrupt a world through impatience — clean shutdown is a correctness requirement, not a nicety.
- Parse stdout into a typed event vocabulary rich enough that M4 needs no changes to the supervisor.
- Establish the filesystem layout M2 will swap versions within and snapshot from.
- Keep the install path free of Node, compilers, and non-base packages.

**Non-Goals:**

- Authentication (LAN-only in v1) — but see the Decisions section; the seam is designed in.
- Multiple Bedrock servers on one host. Single-server assumptions are permitted throughout.
- Java Edition, addons, behavior packs, or experimental features. Vanilla Bedrock only.
- Independent restart of the UI without restarting the game server — explicitly traded away below.
- Any update, backup, config-editing, or player-moderation behavior (M2–M4).

## Decisions

### D1. BDS runs as a direct child of the cobble process

**Chosen:** cobble is a systemd unit; it spawns BDS with `subprocess`/asyncio and holds its stdin and stdout pipes directly.

**Alternatives considered:**

- *BDS as its own systemd unit.* Would let cobble restart without disconnecting players. But stdin then has no natural path — it requires a FIFO with a dummy writer held open to prevent EOF, or a tmux session driven by `send-keys`, or a socat bridge. Each adds an install-time failure mode and a third systemd unit, and stdout must then be read back out of the journal rather than from a pipe. For a Proxmox helper script, that is a meaningful reliability cost.
- *A dedicated supervisor process exposing a Unix socket.* Correct, and the eventual answer if this becomes a real constraint, but it is a third service to install and monitor for a benefit that a LAN family server does not currently need.

**Rationale:** Reboot survival — the stated requirement — is satisfied by cobble having an enabled systemd unit, and is identical under all three options. The only property that actually distinguishes them is whether restarting the panel disconnects players. For a LAN-scale server, a ~30 second interruption when deploying a cobble update is an acceptable price for eliminating all IPC plumbing.

**Consequence to design around:** restarting cobble leaves a player session with a `connected` event and no `disconnected` event. The event model must treat dangling sessions as expected, and M4's roster must reconcile them on startup. This is the same reconciliation an unclean crash requires, so it is not additional work — but it must not be discovered later.

**Migration path:** the HTTP API surface is identical under any supervision model. Moving to a separate supervisor later replaces the internals of one module and changes no route, no event, and no frontend code.

### D2. One process serves both the API and the frontend

**Chosen:** the FastAPI application serves the compiled static bundle and the API from a single uvicorn process, on one port, under one systemd unit.

**Alternatives considered:** a separate web tier proxying to the API. This was the original shape of the idea, motivated by keeping the API as the single source of truth.

**Rationale:** the separation is real and worth keeping *architecturally* — the API remains the only thing that touches BDS, and the frontend is a pure HTTP client with no privileged path. But given D1, restarting the API already restarts the game server, so a separately restartable web tier buys nothing operationally. Serving static files is not a meaningful tier. Collapsing them removes a unit, a port, a proxy configuration, and a class of install-time misconfiguration.

Putting nginx or Caddy in front later requires no application change.

### D3. FastAPI over Flask

Native async suits the two things this service actually does: pumping a subprocess's stdout without blocking, and holding many SSE connections open. Pydantic gives typed validation, which M3 will need for 41 typed configuration keys. The generated OpenAPI schema is genuinely useful when the frontend is a separate TypeScript codebase.

### D4. React + Vite, compiled at build time, no Node at runtime

**Chosen:** React + TypeScript + Vite. `vite build` produces static HTML/JS/CSS; GitHub Actions runs the build on tag and publishes a release tarball containing the Python source and the pre-compiled bundle. The install script downloads that tarball.

**Alternatives considered:** Jinja templates with HTMX/Alpine, which would remove the build step entirely and keep the project single-language. This is genuinely attractive for M3's large configuration form.

**Rationale:** three of this project's surfaces are stateful and real-time — a live console, a live player roster, and a multi-step update state machine with progress. Those are where server-rendered fragment swapping starts to fight the developer. The build-step objection is fully absorbed by CI: the container never sees Node, npm, or a compiler, and the install script only extracts an archive.

### D5. Filesystem layout is chosen now, for M2's benefit

```
/opt/cobble/                    application (python + static/)
/srv/bedrock/
    versions/
        1.26.45.1/              extracted BDS, one dir per version
        1.26.46.1/
    current -> versions/...     symlink; atomic swap target for M2
/var/lib/cobble/                cobble's own durable state
    cobble.db                   (M4 - not created by this change)
/backup/                        default backup destination (M2)
```

Two decisions here exist purely to serve later milestones:

- **The version symlink is established now**, even though only one version will ever exist during M1. Retrofitting a symlink under a running installation is far more disruptive than starting with one.
- **`/var/lib/cobble/` is a directory, and M2 must snapshot the directory rather than an enumerated file list.** M2 ships before M4 creates `cobble.db`. If M2 backs up a list of known files, M4's database silently falls outside the backup set and a restore quietly destroys all player history. Snapshotting the directory makes M4 automatically covered with no revision to M2.

### D6. Stdout is parsed into typed events, not treated as text

The console view could be served by streaming raw lines. It is not, because the same stream is the only source of player history, server-ready signalling, and (in M2) update health checks. Parsing is therefore a foundation concern, and the parser must:

- emit a typed event for each recognised line, retaining the raw line;
- pass unrecognised lines through as raw output rather than discarding them, since Mojang changes log formats between versions and an unparsed line must never become a lost line;
- treat `Server started.` as the readiness signal — M2's post-update health check depends on it, so it is established here.

### D7. Clean shutdown is a correctness boundary

`stop` is written to stdin and BDS is given a generous timeout (default 120 s, configurable) to flush LevelDB and save chunks. On a large world this legitimately takes 20–30 s. SIGKILL is a last resort only.

Any shutdown that required SIGKILL must be **recorded as unclean**. M2 will use that flag to refuse to treat the resulting state as a valid rollback point. Establishing the flag now costs nothing; discovering its absence during an update failure is expensive.

### D8. No authentication, with the seam designed in

v1 is LAN-only and unauthenticated, as specified. To keep this an insertion rather than a rewrite:

- every state-changing operation is an API route (no privileged path bypasses it);
- all such routes sit under a single router with one dependency-injection point, so an auth dependency is added in one place;
- the frontend already treats the API as a remote HTTP service, so introducing credentials changes a client module, not the application's shape.

## Risks / Trade-offs

**Restarting cobble disconnects players (D1)** → Accepted for v1 at LAN/family scale. Mitigated by keeping the API surface supervision-agnostic so the migration is contained; and by making cobble updates a deliberate, infrequent action rather than something that happens automatically.

**Cobble crash takes the game server down with it (D1)** → `Restart=on-failure` on the unit, with the child re-spawned on cobble start. A crash becomes an outage of seconds, not an outage until someone notices.

**SIGKILL tears the LevelDB write-ahead log** → Generous default timeout (D7), SIGKILL only after it expires, and the resulting state flagged unclean so no later mechanism trusts it.

**Mojang changes the stdout log format between versions** → The parser passes unrecognised lines through as raw output rather than dropping them (D6). The console stays correct even when parsing degrades; only derived features lose fidelity, and visibly so.

**The download-links API changes shape or disappears** → It is a single well-isolated function. A version-check failure must be a logged, surfaced non-event that leaves the server running, never a condition that blocks startup.

**Missing User-Agent silently breaks acquisition** → Verified failure mode. The HTTP client sets a UA centrally; this is not left to individual call sites.

**Someone runs this on an ARM host** → BDS has no ARM build; the failure would otherwise be a confusing exec-format error. The install script checks architecture and fails with a clear message.

**Player history only exists from installation onward** → Inherent, not fixable; there is no backfill source. Event parsing therefore ships in M1 even though the roster is M4, so history accumulates from the earliest possible moment.

## Migration Plan

Greenfield; there is nothing to migrate from. Deployment is:

1. Create an unprivileged amd64 Debian 13 LXC (~2 GB RAM), timezone set — an unset timezone will place M2's 04:00 update at an unexpected hour.
2. Install script: verify architecture and glibc, install `python3`, `curl`, `unzip`, fetch the release tarball, create `/srv/bedrock` and `/var/lib/cobble`, install and enable `cobble.service`.
3. First run bootstraps BDS: resolve the current version, download, extract to `versions/<version>/`, point `current` at it.
4. UDP 19132 (and 19133 for IPv6) reachable on the LAN. Bridged networking needs no port forwarding for LAN-only use.
5. `/backup` is a bind mount from the Proxmox host if a NAS is used. Cobble treats it as a path; no NFS or CIFS client code exists in cobble, and mounting is a host-side concern.

**Rollback:** stop and disable the unit; the Bedrock installation under `/srv/bedrock` is untouched by cobble's own removal and remains runnable by hand.

## Open Questions

- **Do console-issued `give` and `effect` require `allow-cheats=true`?** The console runs with operator rights, but whether cheat-gated commands are additionally restricted was not determinable from static inspection. This affects M4's optional "fun toys" tier only; it changes nothing in this change and is cheaply answered once a server is running.
- **Crash-loop policy.** If BDS exits repeatedly on startup, cobble should stop retrying and surface the failure rather than restarting forever. The exact threshold (attempts, window) is a tuning value that does not affect the specs or the task breakdown.
