## Purpose

Interpretation of raw Bedrock server output as structured, typed events, establishing the vocabulary that server status, player history, and later update health checks all consume. Because the Bedrock server keeps no record of player activity, this stream is the only source of that history.

## Requirements

### Requirement: Server output is parsed into typed events

Cobble SHALL parse Bedrock server output into typed events, and SHALL make those events available to consumers separately from raw console output.

#### Scenario: A recognised line produces an event

- **WHEN** the server emits a line matching a known event form
- **THEN** a typed event of the corresponding kind is produced
- **AND** the event carries the fields extracted from that line

#### Scenario: Every event retains its source line

- **WHEN** a typed event is produced
- **THEN** the original unmodified line is retained on the event

### Requirement: Unrecognised output is never discarded

Cobble SHALL pass output it cannot parse through as raw output. Parsing failures SHALL degrade derived features only, never the completeness of the console.

#### Scenario: Unknown line format

- **WHEN** the server emits a line matching no known event form
- **THEN** the line is still delivered to the console stream unaltered
- **AND** no error is raised

#### Scenario: A known line form changes between server versions

- **WHEN** a server version emits a previously recognised line in a changed format
- **THEN** the line remains visible in the console stream
- **AND** cobble continues operating

### Requirement: Player connection events are recognised

Cobble SHALL recognise player connection, spawn, and disconnection output and SHALL extract the player's gamertag and XUID from it.

#### Scenario: Player connects

- **WHEN** the server reports that a player connected
- **THEN** a player-connected event is produced carrying the gamertag and the XUID

#### Scenario: Player disconnects

- **WHEN** the server reports that a player disconnected
- **THEN** a player-disconnected event is produced carrying the gamertag and the XUID

#### Scenario: Player spawns

- **WHEN** the server reports that a player spawned
- **THEN** a player-spawned event is produced carrying the gamertag and the XUID

#### Scenario: XUID is the player identifier

- **WHEN** a player event is produced
- **THEN** the XUID is present as the player's identifier
- **AND** the gamertag is carried as a display name that is not treated as stable

### Requirement: Server readiness is signalled as an event

Cobble SHALL recognise the Bedrock server's startup-complete output and produce a readiness event, which is the signal used to consider the server started.

#### Scenario: Server finishes starting

- **WHEN** the server emits its startup-complete output
- **THEN** a readiness event is produced

#### Scenario: Readiness is not inferred from process spawn

- **WHEN** the server process has been spawned but has not emitted startup-complete output
- **THEN** no readiness event is produced

### Requirement: Events are observable by multiple consumers

Cobble SHALL allow more than one internal consumer to observe the event stream without one consumer's handling affecting another's.

#### Scenario: A consumer fails to handle an event

- **WHEN** one consumer raises an error while handling an event
- **THEN** other consumers still receive that event
- **AND** the Bedrock server is unaffected

#### Scenario: Output processing does not block the server

- **WHEN** the server produces output faster than a consumer handles it
- **THEN** the Bedrock server process is not blocked on its output being consumed

### Requirement: Allowlist enforcement changes are recognised

Because the Bedrock server announces a change to allowlist enforcement but offers no way to query the current state, cobble SHALL parse those announcements into typed events so that enforcement can be tracked by observation.

#### Scenario: Enforcement is turned on

- **WHEN** the server reports that the allowlist has been turned on
- **THEN** an allowlist-enabled event is produced

#### Scenario: Enforcement is turned off

- **WHEN** the server reports that the allowlist has been turned off
- **THEN** an allowlist-disabled event is produced

#### Scenario: The change originated outside cobble

- **WHEN** the announcement follows a command cobble did not issue
- **THEN** the event is produced identically
- **AND** the event does not depend on cobble having caused the change

#### Scenario: The source line is retained

- **WHEN** an allowlist enforcement event is produced
- **THEN** the original unmodified line is retained on the event

### Requirement: Allowlist membership changes are recognised

Cobble SHALL parse the server's announcements of allowlist additions and removals into typed events, so that a change made outside cobble is observed rather than discovered later.

#### Scenario: A player is added

- **WHEN** the server reports that a player has been added to the allowlist
- **THEN** an allowlist-addition event is produced carrying the player's name

#### Scenario: A player is removed

- **WHEN** the server reports that a player has been removed from the allowlist
- **THEN** an allowlist-removal event is produced carrying the player's name

#### Scenario: A name containing spaces

- **WHEN** the announced name contains spaces
- **THEN** the event carries the complete name
