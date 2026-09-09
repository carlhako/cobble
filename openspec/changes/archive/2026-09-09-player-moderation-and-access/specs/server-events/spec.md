## ADDED Requirements

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
