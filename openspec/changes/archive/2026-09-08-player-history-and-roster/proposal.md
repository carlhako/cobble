## Why

Cobble has parsed player connect/spawn/disconnect events since M1 and has never written a single one down. `StatusTracker._online` is an in-memory `dict[str, str]` that is cleared on every state change, so the only player data that exists is "who is online right now". M1 shipped event parsing early on the explicit reasoning that "history not captured is history lost forever — there is no backfill source" (M1 design.md), and then no milestone consumed it. Every restart since installation has discarded that day's history.

This is milestone **M4**, and it is scoped to the half of M4 that needs no new primitives. The roster is a pure consumer of the existing event bus: it requires no interaction with a running Bedrock server, and therefore none of the console command/response layer that M3 identified as the blocker for gamerules and moderation. Those stay deferred.

## What Changes

- **Durable player history.** A SQLite database at `<state_dir>/cobble.db` — the path M1's design reserved — records every observed player session: who, when they connected, when they spawned, when they left, and how the session ended. Written by a new subscriber to the existing event bus.
- **A player roster.** Every player who has ever been observed on this server, with total playtime, session count, first seen, and last seen. Answers "who has played here" and "how long ago was X last on".
- **Session reconciliation on startup.** BDS emits no `Player disconnected` when it is stopped cleanly (verified — see design.md). Open sessions are therefore closed by cobble, which knows both that it is stopping the server and who was online at the time. A periodic checkpoint bounds the loss in the residual case where cobble itself dies without warning.
- **A Players section in the web interface.** The roster, sorted and searchable, with online players distinguished from historical ones, and sessions whose end time was reconstructed rather than observed marked as approximate.
- **The database is made safe to back up.** M2 tars `state_dir` wholesale while cobble is still running, which would capture a live SQLite file mid-write. The backup path gains a checkpoint step before capture.

Not included: any moderation action (kick, ban, op), gamerule editing, and the console command/response layer both require. No authentication — the `auth_guard` seam is unchanged.

## Capabilities

### New Capabilities
- `server-players`: Durable player identity and session history — what a session is, how sessions are opened and closed, how playtime is derived, how sessions orphaned by a restart are reconciled, and what the roster reports.

### Modified Capabilities
- `server-backups`: A backup must capture cobble's database in a restorable state, not merely include its file. Adds a requirement that durable state is quiesced before capture.
- `web-ui-shell`: Adds the Players section — the roster presented in the interface, live-updating, with reconstructed session times visibly distinguished from observed ones.

## Impact

**New code** — a storage module (`cobble/players/`) owning the schema, migrations, and queries; an event-bus subscriber that writes sessions; an API router at `/api/players`; a `Players.tsx` section in the frontend.

**Modified code** — `cobble/runtime.py` (wire the new subscriber and its lifecycle); `cobble/supervisor/` (a hook so a stop closes open sessions before the process goes away); `cobble/backup/capture.py` (checkpoint before tar); `web/src/sections.tsx` (register the section).

**Dependencies** — none added. `sqlite3` is in the standard library. Queries are sub-millisecond at this scale and run on the event loop rather than pulling in an async SQLite driver.

**Data** — creates `<state_dir>/cobble.db`. Already inside M2's backup set by virtue of being in `state_dir`; this change makes that capture consistent rather than incidental. Nothing existing is migrated: there is no prior history to import, and the database begins accumulating from first run.

**Unaffected** — the supervisor's process model, the event vocabulary (`server-events` needs no change; the roster is simply an additional consumer of a bus that already specifies multiple consumers), the update and config machinery, and the authentication posture.
