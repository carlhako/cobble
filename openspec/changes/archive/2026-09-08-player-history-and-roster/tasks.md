## 1. Storage foundation

- [x] 1.1 Create the `cobble.players` package with a storage module that opens `<state_dir>/cobble.db`, enables WAL, and creates the schema idempotently; verify a unit test opens a temporary database twice and finds the schema unchanged the second time
- [x] 1.2 Add a schema-version row and the check that reads it on open; verify a test asserts the version is written on creation and that an unknown future version is refused with a clear error rather than silently used
- [x] 1.3 Define the `players` and `sessions` tables per design.md D8 (xuid primary key, per-session gamertag, connected/spawned/disconnected times, end reason, last-known-active time); verify a test inserts and reads back a session with every field populated and with a null spawn time
- [x] 1.4 Implement session write operations — open a session, record world entry first-write-wins (D3), close a session with an end reason; verify unit tests cover a second world-entry write leaving the first timestamp intact
- [x] 1.5 Implement roster and per-player session queries with totals computed by aggregation (D9); verify tests assert totals equal the sum of session durations and that a player with no closed sessions reports zero rather than an error

## 2. Recording observed sessions

- [x] 2.1 Add an event-bus subscriber that opens a session on a connect event, records world entry on a spawn event, and closes a session on a disconnect event; verify a test feeds parsed events through the bus and asserts the resulting rows
- [x] 2.2 Stamp session times from arrival at the subscriber rather than from the log line, per design.md Context; verify a test asserts the recorded time comes from the injected clock
- [x] 2.3 Make every write failure non-raising and logged, per D7; verify a test with a storage layer that raises on write asserts the bus callback returns normally and the supervisor is unaffected
- [x] 2.4 Start a new session when a player connects with no open session, including a reconnect shortly after a departure (D4); verify a test asserts two distinct sessions and no merging
- [x] 2.5 Wire the subscriber into `runtime.py` alongside `StatusTracker`; verify the runtime starts with the subscriber attached and a connect event recorded end to end

## 3. Closing sessions cobble ends

- [x] 3.1 Add a supervisor hook that fires before the Bedrock process is stopped, carrying the stop time; verify a test asserts it fires for a clean stop and before the process exit is reaped
- [x] 3.2 Close all open sessions from that hook with the `server_stop` end reason (D1 tier 1); verify a test stops the server with two sessions open and asserts both are closed at the stop time
- [x] 3.3 Close all open sessions when the supervisor observes an unexpected exit, with the `server_exit` end reason (D1 tier 2); verify a test simulates an unexpected exit and asserts sessions are closed at the detection time
- [x] 3.4 Verify no session remains open once the server is stopped, for every stop path — manual, maintenance, update, and restart-to-apply-config; verify an integration test exercises each path with a player online

## 4. Reconciling sessions cobble could not close

- [x] 4.1 Periodically update the last-known-active time for open sessions while the server runs; verify a test with a fake clock asserts the field advances at the configured interval and stops advancing when the server stops
- [x] 4.2 On startup, close any session left open by a previous run at its last-known-active time with the `reconstructed` end reason (D1 tier 3), before the subscriber records any new event; verify a test seeds an open session, restarts, and asserts it is closed with the right time and reason and that ordering holds
- [x] 4.3 Prefer the recorded shutdown time over the last-known-active time when it is later and the shutdown record is present; verify a test covers both orderings
- [x] 4.4 Add the checkpoint interval as a documented setting with a default; verify it appears in the settings model and the README configuration table

## 5. Backup consistency

- [x] 5.1 Add a quiesce step that checkpoints and truncates the WAL, exposed for the backup path to call (D6); verify a test asserts the WAL is empty and the main file self-contained afterwards
- [x] 5.2 Call it from the capture path before `state_dir` is read; verify a test captures a backup with the database open and mid-write, restores it into a fresh directory, and asserts it opens and contains every committed session
- [x] 5.3 Fail the backup with a surfaced reason if quiescing fails, rather than capturing unreliable state; verify a test with a failing checkpoint asserts the backup reports failure

## 6. HTTP interface

- [x] 6.1 Add `GET /api/players` returning the roster with display name, total playtime, session count, first seen, last seen, online flag, and an approximate flag; verify an API test asserts the shape and that an empty roster returns an empty list with 200
- [x] 6.2 Add `GET /api/players/{xuid}/sessions` returning that player's sessions most recent first with start, duration, and end reason; verify an API test asserts ordering and that an unknown identifier returns 404
- [x] 6.3 Report the date from which history has been recorded; verify an API test asserts it is present on the roster response
- [x] 6.4 Mount the router with the existing `auth_guard` dependency on any state-changing route (there are none in this change, so verify the read routes remain unauthenticated and consistent with `/api/status`)

## 7. Web interface

- [x] 7.1 Add a `Players` section registered in `sections.tsx`; verify the shell test asserts it appears in navigation alongside the existing sections
- [x] 7.2 Render the roster with online players distinguished, sorted by last seen; verify a component test with fixture data asserts ordering and the online treatment
- [x] 7.3 Present approximate playtimes and reconstructed session ends as approximate, with the reason available (D1, web-ui-shell delta); verify a component test asserts a reconstructed session is marked and an exact one is not
- [x] 7.4 Show a player's session history on selection; verify a component test asserts sessions render most recent first
- [x] 7.5 Update the roster live as players connect and disconnect, using the existing status stream; verify a test drives the fake event source and asserts the roster updates without a reload
- [x] 7.6 Render the empty state and the recorded-since date as explanation rather than error; verify a component test asserts the empty roster message

## 8. Documentation and verification

- [x] 8.1 Document the Players section and the recorded-since behaviour in the README, including that history begins at upgrade and earlier play was never recorded; verify the README renders and the configuration table includes the new setting
- [x] 8.2 Run the full test suite and `ruff` over the files this change touches; verify both pass
- [x] 8.3 Verify on a live server: join, confirm the session appears; leave, confirm it closes as observed; rejoin and stop the server with the player online, confirm the session closes as `server_stop` with no dangling row
- [x] 8.4 Verify reconciliation on a live server: with a player online, terminate cobble abruptly, restart it, and confirm the session is closed as reconstructed within the checkpoint interval
- [x] 8.5 Verify backup consistency on a live server: capture a backup with history present, restore it into a scratch location, and confirm the database opens with the expected sessions
