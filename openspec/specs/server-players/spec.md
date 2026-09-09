## Purpose

Durable record of who has played on this server and for how long — every observed player session, the identity it belongs to, and the playtime derived from it — so that player history survives the restarts, updates and crashes that would otherwise discard it.

## Requirements

### Requirement: Observed player sessions are recorded durably

Cobble SHALL record every player session it observes in durable storage that survives restarts of the Bedrock server, restarts of cobble, and updates to either.

#### Scenario: A player connects

- **WHEN** a player connection is observed
- **THEN** a session is recorded for that player with the time the connection was observed
- **AND** the session is marked as open

#### Scenario: The record survives a restart

- **WHEN** cobble restarts
- **THEN** every session recorded before the restart is still present
- **AND** the playtime derived from those sessions is unchanged

#### Scenario: The record survives an update

- **WHEN** the Bedrock server is updated to a new version
- **THEN** every previously recorded session is still present

### Requirement: A session records connection, entry, and departure separately

A session SHALL record the time the player's connection was observed, the time the player entered the world, and the time the player's session ended, each independently, so that a session which ended before the player entered the world is represented faithfully.

#### Scenario: A player connects, enters the world, and leaves

- **WHEN** a player connects, enters the world, and later leaves
- **THEN** the session records all three times

#### Scenario: A player leaves before entering the world

- **WHEN** a player connects and the session ends without the player having entered the world
- **THEN** the session records the connection and departure times
- **AND** the session records no world-entry time
- **AND** the session is retained rather than discarded

#### Scenario: World entry is reported more than once in a session

- **WHEN** a player is observed entering the world more than once within a single session
- **THEN** the session retains the first observed world-entry time

### Requirement: Players are identified by a stable identifier

Cobble SHALL identify a player by the stable identifier the server reports, and SHALL treat the display name as changeable. A player whose display name changes SHALL remain the same player, with their history intact.

#### Scenario: A player returns with a changed display name

- **WHEN** a player whose sessions were previously recorded connects with a different display name
- **THEN** the new session is attributed to the same player
- **AND** that player's earlier sessions remain attributed to them
- **AND** the player's reported display name is the most recently observed one

#### Scenario: A session's display name is preserved

- **WHEN** a session is recorded
- **THEN** the display name observed at that time is retained with the session
- **AND** a later change of display name does not alter it

### Requirement: A session ends when the player's departure is observed

When a player's departure is observed, cobble SHALL close that player's open session at the observed time and record that the departure was observed directly.

#### Scenario: A player leaves voluntarily

- **WHEN** a player's departure is observed
- **THEN** that player's open session is closed at the observed time
- **AND** the session records that its end was directly observed

#### Scenario: A player reconnects

- **WHEN** a player connects while having no open session
- **THEN** a new session is started
- **AND** the player's previous session is unaffected

#### Scenario: A player reconnects shortly after leaving

- **WHEN** a player departs and connects again a short time later
- **THEN** two distinct sessions are recorded
- **AND** neither is merged into the other

### Requirement: Sessions open when the server stops are closed by cobble

The Bedrock server does not report the departure of players who are online when it shuts down. Cobble SHALL therefore close any session still open when the server stops, without depending on the server to report those departures.

#### Scenario: The server is stopped with players online

- **WHEN** the server is stopped while one or more players are online
- **THEN** every open session is closed
- **AND** each is closed at the time the server stopped
- **AND** each records that it was ended by the server stopping

#### Scenario: The server is stopped as part of scheduled maintenance

- **WHEN** the server is stopped for a scheduled backup or update while players are online
- **THEN** every open session is closed in the same way as any other stop

#### Scenario: The server exits unexpectedly

- **WHEN** the server exits without having been asked to stop, and cobble observes the exit
- **THEN** every open session is closed at the time the exit was observed
- **AND** each records that the server exited unexpectedly

#### Scenario: No session is left open once the server is stopped

- **WHEN** the server is not running
- **THEN** no session is open

### Requirement: Sessions orphaned by cobble's own termination are reconciled

If cobble terminates without the opportunity to close open sessions, those sessions SHALL be closed when cobble next starts, at a time no later than the last point at which the session was known to be active.

#### Scenario: Cobble is terminated without warning while players are online

- **WHEN** cobble starts and finds sessions left open by a previous run
- **THEN** each is closed
- **AND** each is closed at a time no later than the last point the session was known active
- **AND** each records that its end time was reconstructed rather than observed

#### Scenario: Reconciliation completes before new events are recorded

- **WHEN** cobble starts
- **THEN** sessions left open by a previous run are closed before any new session is recorded

#### Scenario: A session's active time is periodically confirmed

- **WHEN** a session is open and the server is running
- **THEN** the time at which it was last known active is updated periodically
- **AND** the interval bounds how much playtime a reconstructed end time can lose

### Requirement: A reconstructed session end is distinguishable from an observed one

Cobble SHALL record how each session ended, and SHALL report a session whose end time was reconstructed as approximate wherever that session or any total derived from it is presented.

#### Scenario: A session's end reason is reported

- **WHEN** a session is reported
- **THEN** it indicates whether it ended by observed departure, by the server stopping, by an unexpected server exit, or by reconstruction after cobble terminated

#### Scenario: A total includes a reconstructed session

- **WHEN** a player's total playtime includes one or more sessions whose end time was reconstructed
- **THEN** the total is reported as approximate

### Requirement: Playtime is derived from recorded sessions

A player's total playtime SHALL be derived from their recorded sessions and SHALL account only for time cobble observed. Playtime for periods during which cobble was not running SHALL NOT be inferred or credited.

#### Scenario: Total playtime is reported

- **WHEN** a player's total playtime is requested
- **THEN** it equals the sum of the durations of that player's closed sessions

#### Scenario: A player is currently online

- **WHEN** a player has an open session
- **THEN** their reported playtime includes the elapsed time of that open session
- **AND** the session is identified as still in progress

#### Scenario: Cobble was not running

- **WHEN** the server was run without cobble observing it
- **THEN** no playtime is credited for that period

### Requirement: Every observed player is reported in a roster

Cobble SHALL report every player it has ever observed, whether or not they are currently online, with their most recently observed display name, their total playtime, their session count, when they were first seen, and when they were last seen.

#### Scenario: The roster is requested

- **WHEN** the roster is requested
- **THEN** it includes every player with at least one recorded session
- **AND** each entry reports display name, total playtime, session count, first seen, and last seen

#### Scenario: A player is currently online

- **WHEN** the roster is requested and a player has an open session
- **THEN** that player is identified as currently online

#### Scenario: A player has never been observed

- **WHEN** a player has no recorded sessions
- **THEN** they do not appear in the roster

#### Scenario: No players have been observed

- **WHEN** the roster is requested and no sessions have been recorded
- **THEN** an empty roster is reported rather than an error

### Requirement: A player's session history is available

Cobble SHALL report the individual sessions recorded for a given player, most recent first.

#### Scenario: A player's sessions are requested

- **WHEN** the sessions for a player are requested
- **THEN** each recorded session is reported with its start time, duration, and how it ended
- **AND** they are ordered most recent first

### Requirement: Recording player history never disrupts the server

Failure to record player history SHALL NOT interrupt the Bedrock server, the console, or any other cobble function. A recording failure SHALL be logged and surfaced, and SHALL leave history incomplete rather than causing a wider failure.

#### Scenario: Durable storage cannot be written

- **WHEN** a session cannot be recorded
- **THEN** the failure is logged
- **AND** the server continues running
- **AND** console output continues to be streamed

#### Scenario: Durable storage is unavailable at startup

- **WHEN** player history cannot be opened at startup
- **THEN** the failure is surfaced
- **AND** the server still starts

### Requirement: History begins when recording begins

Player history SHALL cover only the period during which cobble has been recording it. Cobble SHALL make the start of the recorded period visible so that an absence of early history is distinguishable from a loss of it.

#### Scenario: History is reported for an installation that predates recording

- **WHEN** the roster is presented on an installation that ran before player history was recorded
- **THEN** the date from which history has been recorded is reported

### Requirement: A session ended by a kick is attributed to it

Because a departure caused by a kick is indistinguishable from a voluntary one in the server's output, cobble SHALL attribute a session it ended by kicking the player, so that the roster records why the session ended.

#### Scenario: A kicked player's session is closed

- **WHEN** a player departs following a kick cobble issued for that player
- **THEN** that player's session is closed at the observed time
- **AND** the session records that its end was caused by a kick

#### Scenario: A voluntary departure is not attributed to a kick

- **WHEN** a player departs and cobble issued no kick for that player
- **THEN** the session records its end as directly observed
- **AND** the session is not attributed to a kick

#### Scenario: A departure arrives long after a kick

- **WHEN** a player departs more than a bounded time after a kick cobble issued for them
- **THEN** the session records its end as directly observed
- **AND** the session is not attributed to a kick

#### Scenario: A kicked session's playtime is exact

- **WHEN** a session ended by a kick is reported
- **THEN** its duration is treated as exact rather than approximate

### Requirement: A player's access state is reported with their roster entry

Cobble SHALL report, for each player in the roster, whether they are permitted to join, whether they are banned, and what permission level they hold, so that an operator sees a player's standing alongside their history.

#### Scenario: The roster is requested

- **WHEN** the roster is requested
- **THEN** each entry reports whether that player is permitted to join
- **AND** each entry reports whether that player is banned
- **AND** each entry reports the permission level that player holds

#### Scenario: A player is banned

- **WHEN** a banned player's roster entry is reported
- **THEN** the reason for the ban and when it was applied are reported with it

#### Scenario: The allowlist is not being enforced

- **WHEN** the roster is requested while allowlist enforcement is off
- **THEN** each entry still reports whether the player is on the allowlist
- **AND** the report distinguishes being permitted from the allowlist having no effect

#### Scenario: A permitted player has never played here

- **WHEN** a player is on the allowlist and has no recorded sessions
- **THEN** they are reported separately from the roster
- **AND** they are not reported as having played on this server

### Requirement: Moderation actions are available for a player

Cobble SHALL allow a player in the roster to be kicked, banned, unbanned, and given or refused operator rights, identified by the stable identifier the roster uses.

#### Scenario: An action is requested for a roster player

- **WHEN** a moderation action is requested for a player in the roster
- **THEN** the action is applied to the player that identifier denotes
- **AND** the action does not depend on the player's current display name being unchanged

#### Scenario: The player's name has changed since they last played

- **WHEN** an action is requested for a player whose display name has changed
- **THEN** the action applies to the same player
- **AND** the name currently in use is the one conveyed to the server where a name is required

#### Scenario: An action is requested for an unknown player

- **WHEN** a moderation action is requested for an identifier with no recorded sessions
- **THEN** the request is refused with a reason
