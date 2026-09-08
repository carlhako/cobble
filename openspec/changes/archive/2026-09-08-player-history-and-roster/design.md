## Context

See proposal.md — Why. The constraints below come from decisions already made in M1–M3, plus one behaviour verified empirically against a live server on 2026-09-08 (BDS 1.26.45.1).

- **The event vocabulary is sufficient and already multi-consumer.** `PlayerConnected`, `PlayerSpawned` and `PlayerDisconnected` carry `xuid` and `gamertag`, and the `server-events` spec already requires that events be observable by multiple consumers. The roster is a new subscriber, not a change to the bus.
- **Events carry no timestamp.** `Event` has only `raw`; `patterns.py` tolerates BDS's `[YYYY-MM-DD HH:MM:SS:mmm INFO]` prefix but discards it. Because cobble spawns BDS itself there is never a backlog to replay, so arrival time at the subscriber is the event time.
- **`xuid` is the identity; `gamertag` is not stable.** Stated in M1's design ("BDS keeps no player database") and in `events/model.py`.
- **BDS is a direct child of cobble and cannot outlive it.** Cobble never attaches to a server it did not spawn. Every session in the database therefore belongs to a run cobble observed from the start.
- **`state_dir` is tarred whole, with the server stopped but cobble still running** (`backup/capture.py`, `sources = {CONTENT_DATA: …, CONTENT_STATE: layout.state_dir}`). M2's D5 reasoned that snapshotting the directory means `cobble.db` is "automatically covered". It is included, but inclusion is not consistency.

### Verified: a clean stop emits no disconnects

The central unknown when this change was scoped was whether BDS reports per-player disconnects when it is stopped. It does not. With one player online, `POST /api/server/stop` produced:

```
seq 83  04:36:22.289  Player Spawned: Matthew1396 xuid: 2533275031569649, pfid: …
seq 84  04:38:36.126  Server stop requested.
seq 85  04:38:36.135  Stopping server...
seq 86                Quit correctly
```

No `Player disconnected` line, then or later. In the same capture a *voluntary* leave did produce one, so the parser and the stream are not at fault — BDS simply does not report the players it drops on shutdown.

This makes reconciliation the normal path rather than an edge case. Cobble restarts the server routinely and automatically: the 04:00 maintenance window, an applied update, a restart to apply pending configuration, and crash auto-restart all orphan every open session. A design that treated orphaned sessions as rare would be wrong about the common case.

Two secondary observations from the same capture:

- `Player Spawned` fired exactly once per session across two sessions. Treated as "expected once" rather than guaranteed once — see D3.
- The connect→spawn gap was 7.16 s and 5.05 s: real, but immaterial against session lengths measured in hours. See D2.
- `Quit correctly` arrives with no log prefix at all, confirming the existing optional-prefix handling in `patterns.py`.

## Goals / Non-Goals

**Goals:**

- Player history accumulates from this change forward and survives restarts, updates, crashes, and restores.
- Playtime for a session that cobble ended is exact, not estimated.
- A session whose end time was reconstructed rather than observed is distinguishable as such, everywhere it is displayed.
- A backup captures the database in a state that restores cleanly.
- Nothing in the write path can stall or crash the supervisor.

**Non-Goals:**

- Backfilling history from before this change. There is no source; the database starts empty.
- Attributing playtime for any period cobble was not running. Playtime is what cobble observed, not what the world log implies.
- Per-world or per-dimension playtime, position, inventory, or anything requiring the world database.
- Any write to the game (moderation, gamerules) — deferred with the command/response layer.
- Authentication on the new routes beyond the existing `auth_guard` seam.

## Decisions

### D1. Sessions are closed by cobble, in three tiers, not inferred from BDS

Because BDS reports nothing on shutdown (see Context), the naive approaches are all bad: dropping orphaned sessions steals playtime, and crediting them to "now" on the next startup invents hours that nobody played. But cobble does not need BDS to tell it. Cobble *initiates* the stop and already holds the online roster in `StatusTracker._online`. The information is present; it is currently just discarded.

| Tier | Situation | How the session is closed | Accuracy |
|---|---|---|---|
| 1 | Cobble stops the server (maintenance, update, config restart, manual) | Cobble closes open sessions at stop time, before the process is gone | Exact |
| 2 | BDS exits on its own; cobble is alive and observes it | Cobble closes open sessions at exit-detection time | Exact to within detection latency |
| 3 | Cobble itself dies without warning (SIGKILL, OOM, power loss) | On next startup, close at the last checkpoint | Bounded by the checkpoint interval |

Tiers 1 and 2 cover everything that happens in normal operation, and both are exact. That demotes tier 3 from load-bearing to a backstop for genuine power loss, which in turn means the checkpoint interval can be lazy — minutes, not seconds — costing a trivial write while the server is occupied.

Each session records how it ended (`end_reason`), so tier-3 reconstructions are marked at the row level and stay marked through every query and view that touches them.

**Alternative considered — heartbeat only, no stop hook.** Simpler (one mechanism), but makes every routine restart lose up to a full interval of playtime for every online player, on the most common path. Rejected: it degrades the common case to buy simplicity in the rare one.

**Alternative considered — synthesise disconnect events into the bus at stop.** Would let the roster stay a pure event consumer. Rejected: it puts fabricated lines in a stream specified to represent observed server output, and the console would display disconnects BDS never emitted.

### D2. Connect, spawn, and disconnect times are all stored; playtime is derived from connect→disconnect

Measured connect→spawn latency is 5–7 s. Against a session of any real length that is fractions of a percent, so the choice does not warrant a mechanism. Connect→disconnect is chosen because those two are the pair that always exists and it matches how `online_players` is already defined in `server-status`.

All three timestamps are stored regardless, because the data is free at write time and unbackfillable later. If spawn-based playtime is ever wanted, it is a query change against data already collected rather than a year of history that cannot be recovered.

A session that connected but never spawned (a player who quit during the 5–7 s load) is retained with a null spawn time. It is a real connection and correctly contributes near-zero playtime.

### D3. `spawned_at` is first-write-wins

Spawn fired once per session in the observations, but the sample is two sessions and dimension changes and deaths were not exercised. Should BDS emit a second `Player Spawned` within a session, first-write-wins keeps the session start honest and cannot corrupt anything. The cost is one conditional; the alternative risks silently resetting a session's clock.

### D4. A reconnect always starts a new session

The captured data included a 6.24 s disconnect→reconnect. Merging sessions across a short gap would need a threshold that is arbitrary at any value, and would make session counts wrong in the opposite direction. Strict sessions are honest and simple.

The consequence is that a player on unstable networking accumulates many short sessions. This is a presentation problem, not a data problem: the roster leads with total playtime and last seen, and treats session count as a secondary detail.

### D5. SQLite from the standard library, called synchronously

`sqlite3` ships with Python, so the "no compiler, wheels only" install constraint is untouched and no dependency is added. M1's design already reserved the path `<state_dir>/cobble.db`.

Writes are a handful of rows per hour; reads are aggregations over a table that will hold thousands of rows after years of family-scale use. At that size queries are sub-millisecond, and blocking the event loop for that long is not worth an `aiosqlite` dependency and an async migration of the call sites. If the roster ever becomes slow enough to matter, moving these calls to a thread pool is a contained change behind the storage module's interface.

WAL mode is enabled: it keeps the writer from blocking readers, and it is what makes D6's checkpoint a meaningful operation.

**Alternative considered — an append-only JSONL log.** No dependency at all and trivially crash-safe, but every roster query becomes a full scan and aggregation in Python, and closing orphaned sessions means rewriting or tombstoning records in a file format with no update semantics. Rejected: SQLite costs nothing here and does all of this correctly.

### D6. The database is checkpointed before a backup captures `state_dir`

M2 captures `state_dir` as a directory specifically so that this database would be included without revising the backup code. That reasoning holds for *inclusion*, but a backup runs with BDS stopped and **cobble still running**, so the tar reads a live SQLite file. In WAL mode the `-wal` and `-shm` sidecars may be inconsistent with the main file at the instant each is read, and a restore can yield a database missing recent transactions or refusing to open.

The backup path therefore checkpoints and truncates the WAL before capture, so the main file is self-contained and the sidecars are empty. This is a small addition to a path that already stops the server and already knows it is about to read `state_dir`.

Left unfixed this is invisible for a long time and then destroys the one dataset in the system that cannot be rebuilt — which is precisely the failure M2's D5 was trying to prevent.

### D7. The roster is a subscriber, and its failures are contained

The writer subscribes to the event bus like `StatusTracker` does. The bus contract requires callbacks to be fast and non-raising, and that is not negotiable here: a database problem must never propagate into the supervisor or stall the console. Write failures are logged and dropped, and the roster degrades to incomplete history rather than taking the server down. Losing a session record is bad; losing the game server because history could not be written is worse.

### D8. `xuid` is the primary key; gamertags are recorded per session

The players table is keyed on `xuid` with the most recently observed gamertag denormalised onto it for display and search. Each session additionally records the gamertag as seen at the time, so a rename does not rewrite history and the rename is itself recoverable from the session rows. No separate rename log is needed.

### D9. Totals are computed, not stored

Total playtime and session count are aggregates over the sessions table rather than counters on the players row. At this scale the aggregation is free, and a stored total is one more thing that can drift out of agreement with the sessions it summarises. Drift in the only unbackfillable dataset in the system is not a trade worth making for a saved microsecond.

## Risks / Trade-offs

**A restart orphans sessions between the stop hook and the process actually exiting** → Tier 1 closes sessions at stop time, before the process is reaped, so the window does not exist for cobble-initiated stops. Tier 2 covers the rest.

**Cobble is SIGKILLed with players online** → Up to one checkpoint interval of playtime is lost for those players and the sessions are marked reconstructed. Bounded, visible, and rare.

**A restore rewinds the database to the backup's contents** → Any history between the backup and the restore is lost, consistent with how every other restored artifact behaves. Sessions open at capture time are closed as reconstructed on the next startup rather than left dangling forever.

**Mojang changes the player line formats** → Parsing degrades to `RawOutput` exactly as it does today, and the roster stops gaining sessions while the console stays correct. The existing "never discard" rule means the raw lines survive in the console buffer; it does not mean history can be recovered from them, so a format change is a real (if visible) loss of history until the patterns are updated.

**A player renames and the roster looks like it lost someone** → Identity is `xuid`, so the history follows the rename; only the display name changes. Per-session gamertags make the transition legible rather than confusing.

**Writing on the event loop** → Bounded by the size of the data and the rate of events, both tiny. Contained behind the storage module if that ever stops being true (D5).

## Migration Plan

There is no data to migrate. The database is created on first start if absent and begins accumulating immediately.

1. Ship with the schema created idempotently at startup, guarded by a schema-version row so later changes have a defined upgrade point.
2. On every startup, before accepting new events, close any session left open by a previous run (tier 3 of D1) so no row is dangling once startup completes.
3. A pre-existing installation gains a Players section that is empty apart from whatever accrues from that moment. This is expected and should be stated in the UI rather than looking like a bug — an operator who has been running cobble for months will otherwise reasonably assume history was lost rather than never collected.

**Rollback:** the change is additive. Reverting leaves an unused `cobble.db` in `state_dir`, which is harmless and remains inside the backup set. No existing file format or path changes.

## Open Questions

- **Checkpoint interval for tier 3.** A tuning value bounded by "small enough that power-loss error is uninteresting, large enough to be free". It affects no spec, no schema, and no task.
- **Whether `Player Spawned` can repeat within a session** (dimension change, death). D3 makes cobble correct either way, so this can be answered from accumulated data later rather than blocking the change.
- **Whether `pfid` is a more stable identifier than `xuid`.** The unparsed `Player PartyIdUpdate` line carries `pfid` at connect time, and disconnect and spawn carry it too, so adopting it later is possible without new parsing work. `xuid` is what M1 specified and there is no evidence it is insufficient.
