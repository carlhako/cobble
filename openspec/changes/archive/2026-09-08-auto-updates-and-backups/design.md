## Context

See proposal.md — Why. This section records only the constraints that shape the approach; several were established in M1's design for exactly this milestone.

**What M1 already established for M2** (archived `cobble-foundation/design.md`):

- `versions/<v>/` one directory per version, `current` symlink as the atomic swap target (D5).
- `Server started.` is the readiness signal, parsed into a typed event (D6) — the post-update health check is meant to consume it.
- Any shutdown that needed SIGKILL is recorded as unclean (D7) so M2 can refuse to treat the resulting state as a valid rollback point.
- `/var/lib/cobble/` is a directory and the unit of capture for backups; `installation` already says a consumer capturing it must pick up files added later without being changed.
- The resumable ~100 MB downloader (`acquisition/installer.py`) and the vendor version resolver (`acquisition/version_source.py`) handle a flaky CDN and are reused here unchanged.

**BDS constraints relevant to layout:**

- BDS resolves `server.properties`, `worlds/`, `allowlist.json`, `permissions.json`, `definitions/`, and the default packs **relative to its working directory**. There is no flag to relocate them.
- BDS upgrades a world's on-disk format forward when a newer version loads it, and never downgrades. A world touched by version N cannot be handed back to version N-1.
- The vendor publishes only the *current* version — no history endpoint, no pinning. A version that has been superseded cannot be re-downloaded.

**Current layout problem:** the world and every config file live inside `versions/<v>/`. An update that swaps `current` to a new version directory strands them. M2 must fix the layout before it can update anything.

## Goals / Non-Goals

**Goals:**

- A stable on-disk home for the world and config that a version swap does not touch, so update and backup both target fixed paths.
- Unattended updates that never leave the server on a broken version: every update is reversible to the state that preceded it.
- A world that is always recoverable — a verified backup exists before anything destructive runs, and a captured backup can be restored from the interface.
- Reuse M1's supervisor, downloader, event parser, and shutdown guarantees rather than re-implementing them.

**Non-Goals:**

- Choosing or pinning a target Bedrock version. Updates track the vendor's current release only.
- Rolling back more than one version. The immediately previous version is the only retained rollback source.
- Backing up to remote storage protocols. `COBBLE_BACKUP_DIR` is a plain path; mounting is a host concern (unchanged from M1).
- Incremental or deduplicated backups. Each backup is a self-contained capture.
- Zero-downtime backups. Captures are cold and share the nightly maintenance window (D7); hot capture via BDS `save hold` is a later refinement, not part of M2.
- Running a second Bedrock instance to validate an update before or after applying it (D4, rejected alternative). M1's non-goal — multiple servers on one host, with single-server assumptions permitted throughout — therefore stands unqualified: cobble supervises exactly one Bedrock process at all times.
- Carrying operator-added resource/behaviour packs across a version update — deferred until the pack story is designed (M3-adjacent).

## Decisions

### D1. Mutable state is pulled out of the version directory

**Chosen:** introduce `/srv/bedrock/data/` as the stable home for the world, `server.properties`, `allowlist.json`, and `permissions.json`. A version directory under `versions/<v>/` holds only vendor payload and is disposable.

**Alternative considered — migrate-on-update:** leave the layout as-is and have each update copy `worlds/` and the config files from the old version directory into the new one before swapping `current`. Rejected: it puts a full rewrite of the world onto the hot path of every update, and it keeps a hand-maintained "which files carry forward" list whose failure mode is silent data loss — a file omitted from the list is deleted with the old version directory on the next update.

**Rationale:** a fixed path for mutable state makes the backup target trivial (two directories, no enumeration), makes `current` a pure pointer again, and means an update touches no world data at all on the success path.

**Consequence to design around:** this is an on-disk layout change. Existing M1 installations have their world inside `versions/<v>/` and must be migrated once (D3).

### D2. Wiring: the working directory is `data/`, vendor payload is symlinked in

**Chosen (B-inverted):** cobble spawns BDS with `cwd=/srv/bedrock/data`. `data/` contains the real mutable files and directories, plus symlinks for the vendor payload that point through `current`:

```
/srv/bedrock/
    versions/1.26.46.1/            pure vendor payload, one dir per version, disposable
    current -> versions/1.26.46.1  the only thing an activation changes
    data/
        server.properties         real   (operator state)
        allowlist.json            real
        permissions.json          real
        worlds/                   real   (LevelDB; stable path across versions)
        bedrock_server  -> ../current/bedrock_server
        definitions     -> ../current/definitions
        resource_packs  -> ../current/resource_packs
        behavior_packs  -> ../current/behavior_packs
        ...                       (exact vendor-payload set: see Open Questions)
```

Activating a version is `os.replace` on the `current` symlink and nothing else — the `data/` symlinks resolve through `current`, so they never need recreating.

**Alternative considered — B1 (symlink mutable entries out of the version dir):** keep `cwd=versions/<v>/` and replace `server.properties`, `worlds`, etc. inside it with symlinks pointing to `../../data/`. Rejected: the symlink set must be recreated in every new version directory as part of install/activate, and its failure mode is silent — a mutable entry not in the list stays a real file in the version directory and is lost on the next update. B-inverted's failure mode is loud: omit a vendor directory from the symlink set and BDS fails to start on that path immediately, before any data moves.

**Consequence to design around:** the complete list of vendor-payload entries BDS expects in its working directory must be known and kept correct. This is a spike against a real extracted tree (Open Questions).

### D3. Existing installations are migrated once, backup-first, on first M2 start

**Chosen:** on startup, if the layout is still M1-shaped (`current/worlds` is a real directory, no `data/`), cobble performs a one-time migration: require the server stopped, take a full backup, move `worlds/` and the config files from the active version directory into `data/`, create the vendor-payload symlinks, and record that migration completed. The migration is idempotent — a run interrupted part-way resumes without data loss.

**Alternative considered — operator-confirmed migration:** surface "this installation needs relocating" in the interface and wait for a click before moving anything. Rejected: it leaves a freshly upgraded deployment refusing to start until someone notices a button, which contradicts the "reaches a running server with no manual steps" property M1 established. The migration is also not a judgement call — there is exactly one correct outcome — so a prompt would ask a question with only one answer.

**Rationale:** a verified backup taken before the move is the safety net that makes an unattended move acceptable. The migration runs once, logs each step, and records completion so it never runs again.

### D4. The update is a state machine with a mandatory verified backup and a rollback path

**Chosen sequence:**

```
resolve current vendor version
  |
  +-- not newer, or newer but quarantined (see below) --> record result, stop
  |
newer:
  download + extract into versions/<new>/     <-- SERVER STILL RUNNING; no downtime
      (M1 downloader/extractor, unchanged)
      fails --> ABORT; nothing was touched
  |
--------------------------- maintenance window opens ---------------------------
  clean stop (M1 shutdown path)
      recorded unclean / needed SIGKILL (D7)
          --> ABORT, restart the old version, surface
              (never build a rollback point on torn LevelDB)
  |
  cold backup of data/ + /var/lib/cobble/, then verify it
      fails --> ABORT, restart the old version, surface
  |
  swap current -> versions/<new>
  |
  start, await readiness within readiness_timeout   (M1 readiness event)
  |
  +-- ready --> success; prune version dirs, keeping versions/<previous>
  |
  +-- readiness timeout, or exit before readiness, or crash inside the grace window
        --> ROLLBACK, automatically:
              swap current -> versions/<previous>
              restore worlds/ from the pre-update backup
              start the previous version
                |
                +-- ok   --> quarantine <new>; surface "update failed, rolled back"
                +-- fail --> TERMINAL: stop attempting anything further, change
                             nothing else, surface loudly. Operator intervention
                             is required only here.
--------------------------- maintenance window closes --------------------------
```

**Rationale:** each step reuses an M1 guarantee, and the ordering minimises downtime and blast radius. The download is the slowest and least reliable step (a ~100 MB transfer from a CDN M1 documents as stall-prone) but it is also entirely non-destructive — it writes only into a new directory — so it runs while the server is still serving players. Downtime is therefore stop + backup + start, and never includes the transfer.

The pre-update backup is load-bearing, not best-effort: it is the only way to undo a world-format upgrade (Context: BDS never downgrades a world), so an update cannot proceed past a backup that will not verify. It is taken *after* the clean stop because backups are cold (D7) and a stopped server is what makes the copy consistent.

**Rollback always restores the world, even when the new version never signalled readiness.** BDS upgrades the world format during level load, which completes before `Server started.` is printed — so a version that died during load may already have partially upgraded the world. Cobble cannot distinguish that case, so it always restores rather than trusting the on-disk copy. This costs nothing: the backup was captured minutes earlier with the server already stopped, so no playtime is lost.

**A version that fails its health check is quarantined.** Without this, the next scheduled run sees the same version still advertised as current upstream and repeats the entire failed update — a nightly outage in a loop. A quarantined version is skipped by the scheduler until the vendor publishes a different version, or an operator clears it. Its directory is retained for diagnosis rather than pruned.

**The failed attempt's output is retained and surfaced.** A failed update records which version was attempted, which step it failed at, and the console output captured from the attempt, and the interface presents them as an alert rather than only a status flag. No new capture mechanism is needed: M1 already retains the output leading to a readiness-timeout failure and the exit code and preceding output for a crash (`server-lifecycle`). M2 attributes that existing record to the update that produced it and gives it somewhere to be seen.

**Alternative considered — validate the new version in parallel before committing to it.** BDS instances can coexist on one host if given different `server-port`/`server-portv6` values, so cobble could extract the new version into a temporary directory and start it on scratch ports — either as a pre-flight before every update, or as a diagnostic re-run after one failed — and only then trust it. It cannot share the live world (LevelDB holds an exclusive lock), so such a probe would run against a copy taken from the most recent backup.

Rejected for M2, on grounds of value rather than difficulty: the failed real attempt has *already* produced the console output that a probe would be re-generating, so the diagnostic payoff over simply surfacing that output is small. The information a probe adds beyond it — distinguishing a broken binary from something specific to the live world — is not information an operator would act on differently, since the remedy in both cases is to wait for the vendor's next release. Against that, a probe is a second BDS process spawned at the most delicate moment, on a container specified for one (~2 GB), where memory pressure could see the kernel kill the live server and convert a contained failure into an outage.

Recorded here rather than discarded: if update failures prove common in practice, the parallel probe is the natural next step, and its constraints — exclusive world lock, world copy from a backup, memory headroom check, a lightweight readiness probe rather than a second `Supervisor` — are already worked out.

**Consequence to design around:** the update owns all restart decisions inside the maintenance window. M1's automatic crash restart (threshold 3 in 300 s) would otherwise race the rollback — restarting the failing new version while the update logic is trying to revert it. Suspending crash-auto-restart for the window is the responsibility of the maintenance flag (D8).

### D5. The previous version directory is the only retained rollback source

**Chosen:** after a successful update, keep `versions/<previous>/` and prune anything older. Rollback beyond one version is not supported.

**Rationale:** the vendor publishes only the current version, so a superseded version cannot be re-fetched. The previous directory on disk is the entire rollback capability; pruning it would make the immediately-prior state unrecoverable, and keeping a long tail of versions wastes ~100 MB each for no reachable use.

### D6. Backup capture target is two stable directories

**Chosen:** a backup captures `/srv/bedrock/data/` (world + config) and `/var/lib/cobble/` (cobble's own state), plus a manifest recording the timestamp, the installed Bedrock version, and whether the last shutdown was clean. Restore swaps a captured `data/` back into place after setting the current one aside (itself captured first).

**Rationale:** D1 made this possible — no file enumeration, no per-version knowledge. `installation` already designates `/var/lib/cobble/` as a unit of capture; this extends the same treatment to `data/`. The manifest's version field lets restore refuse or warn when a backup's world predates the installed binary by more than the vendor allows.

### D7. Backups are cold, and share the update's maintenance window

**Chosen:** a backup is taken with the server stopped — stop, copy, start — and the scheduled backup runs in the same nightly window as the update check, so a night that updates incurs one outage rather than two. The pre-update backup in D4 is the same mechanism, already inside its stop.

**Alternative considered — hot backup via BDS `save hold` / `save query` / `save resume`:** BDS can quiesce writes and report the exact set of files to copy, giving a consistent capture with no downtime. Rejected for M2: it means driving a multi-step command exchange through the console channel and parsing its replies, with a failure mode (the hold never released) that leaves the server unable to save. That is meaningful complexity to avoid a brief outage at 04:00 on a family LAN server that is not being played at the time.

**Consequence to design around:** the nightly window is a single ordered sequence — backup, then update if one is available — not two independent schedules that could overlap. Hot backup remains a clean later refinement if the outage ever becomes a problem; it changes the capture mechanism only, not the format, schedule, or retention.

### D8. Maintenance is a flag orthogonal to `RunState`, not a new run state

**Chosen:** an update or restore in progress is represented by a separate observable field (`maintenance: updating | restoring | null`) alongside the existing `RunState`. While it is set, cobble rejects conflicting operator lifecycle actions and suspends automatic crash restart.

**Alternative considered — a new `RunState.UPDATING`:** rejected because `RunState` describes the *Bedrock process*, and an update legitimately moves that process through `running → stopping → stopped → starting → running`. Modelling the update as one of those values would require the state machine to leave and re-enter it repeatedly, breaking M1's transition table (`supervisor/state.py`) and the guards built on it.

**Rationale:** the two axes answer different questions — "what is the server process doing" and "is cobble in the middle of a multi-step operation" — and keeping them separate leaves M1's state machine untouched. The flag also carries the responsibility identified in D4: while it is set, the update owns restart decisions, so crash-auto-restart must not fire.

### D9. Update mode: applied automatically on schedule, with a manual check

**Chosen:** the scheduled run (default around 04:00 local time) applies an available update automatically, and the interface additionally offers a "check for updates now" action that runs the same sequence on demand.

**Rationale:** notify-and-confirm would leave the server on an outdated version until an operator noticed, which defeats the milestone's purpose — a Bedrock server that lags the client version rejects players. Automatic application is only defensible because D4 makes every update reversible without human involvement; the two decisions depend on each other.

### D10. The scheduler runs in-process

**Chosen:** an asyncio task inside cobble computes the next run in local time and sleeps until it, rather than a systemd timer invoking a cobble subcommand.

**Alternative considered — a systemd timer:** would survive cobble being down and gives the operator a familiar handle, but requires a second unit, a CLI entry point, and an IPC path for a subcommand to drive the running supervisor — precisely the install-time complexity M1's D1 rejected for the same reason.

**Rationale:** cobble is already a long-lived supervised process that is meant to be running at all times; a schedule it owns needs no additional installed units. The next resolved run time is exposed in status so a misconfigured container timezone is visible rather than silent.

### D11. A failed scheduled backup is surfaced, never silently disabling the schedule

**Chosen:** a scheduled backup that cannot write to `COBBLE_BACKUP_DIR` (unmounted, full, read-only) records the failure, surfaces it as an unhealthy state in status and the interface, and leaves the schedule enabled so the next run retries. It does not disable itself after repeated failures.

**Rationale:** the worst outcome for a backup system is silently ceasing to back up. A persistent loud failure is recoverable — an operator fixes the mount and the next run succeeds; a self-disabled schedule looks identical to a healthy one until the day it is needed. This is distinct from the *update* path, where a backup that will not verify aborts the update outright (D4): there, failing closed protects the world; here, failing open preserves visibility.

## Risks / Trade-offs

- **The migration (D3) moves a live world** → A verified backup is taken before the move, the server must be stopped, and the move is idempotent. The migration logs loudly and records completion so it never runs twice.
- **A vendor-payload entry is missing from the D2 symlink set** → BDS fails to start on that path immediately; caught by the spike and by the update's own health check before the old version is pruned.
- **World-format upgrade makes a version rollback destructive** → Rollback restores `worlds/` from the pre-update backup rather than trusting the on-disk copy the new version already touched (D4).
- **`COBBLE_BACKUP_DIR` is unmounted, full, or read-only** → On the update path the pre-update backup fails to verify and the update aborts with the server untouched (D4). On the scheduled path the failure is surfaced as an unhealthy state and the schedule keeps retrying (D11).
- **Scheduled update fires while an operator is on the console** → The maintenance flag (D8) rejects conflicting lifecycle actions with a clear reason rather than interleaving them.
- **M1's crash-auto-restart races the rollback** → The maintenance flag suspends automatic restart for the duration of the window, so the update alone decides when the server is restarted (D4, D8).
- **A broken vendor release triggers a nightly outage loop** → A version that fails its health check is quarantined and skipped by the scheduler until the vendor publishes a different version or an operator clears it (D4).
- **Rollback itself fails to start the previous version** → Cobble stops attempting recovery, changes nothing further, and surfaces the failure loudly. This is the single path in M2 that requires operator intervention, and it is deliberately inert rather than continuing to act on a system in an unknown state.
- **Clock or timezone unset in the container** → A schedule expressed in local time runs at the wrong hour. Already called out as a container prerequisite in the README; the interface should surface the resolved next-run time so the misconfiguration is visible.
- **Vendor download-links API changes shape or is unreachable at 04:00** → Reuses M1's non-raising resolver: a failed check is a logged non-event, the server keeps running, the next scheduled check retries.

## Migration Plan

**Deploy:** ship as a normal cobble release. On first start of the new version against an M1-shaped layout, D3's migration runs (backup, move to `data/`, symlink, mark done). A fresh install lays out `data/` directly during bootstrap and never migrates.

**Rollback (of cobble itself, not Bedrock):** the pre-migration backup captured in D3 contains the world in its original location. Reverting to the M1 cobble release additionally requires moving `data/worlds/` and the config files back into the active version directory and removing the symlinks — a documented manual step, since the M1 release has no knowledge of `data/`.

**Forward:** once migrated, `data/` is the permanent layout; M3 and M4 build on it.

## Open Questions

One item remains, and it blocks implementation rather than the specs phase — a spec states that vendor payload is linked into the working directory without enumerating it.

1. **Vendor-payload inventory + symlink sanity (spike).** The complete set of files and directories BDS expects in its working directory, taken from a freshly extracted 1.26.x tree (`bedrock_server`, `definitions/`, `resource_packs/`, `behavior_packs/`, `premium_cache/`, `valid_known_packs.json`, `structures/`, `config/`, …), plus confirmation that BDS writes LevelDB correctly when `worlds/` is a real directory inside a working directory otherwise composed of symlinks. Resolved by extracting a release on the target LXC and listing its top level; must be answered before D2 can be implemented, and the resulting list belongs in the task breakdown rather than in a spec.
