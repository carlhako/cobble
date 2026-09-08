## ADDED Requirements

### Requirement: The player roster is available from the interface

The interface SHALL present the players who have been observed on this server, showing for each their display name, total playtime, when they were last seen, and whether they are currently online. Players currently online SHALL be distinguishable from those who are not.

#### Scenario: The roster is viewed

- **WHEN** the operator opens the players section
- **THEN** every observed player is listed with display name, total playtime, and when they were last seen
- **AND** players currently online are distinguished from those who are not

#### Scenario: A player's sessions are inspected

- **WHEN** the operator selects a player
- **THEN** that player's individual sessions are shown, most recent first, each with its start time, duration, and how it ended

#### Scenario: A player connects or disconnects while the roster is open

- **WHEN** a player connects or disconnects
- **THEN** the roster reflects the change without operator action

#### Scenario: No players have been observed

- **WHEN** the players section is opened and no players have been observed
- **THEN** the interface explains that no player history has been recorded yet
- **AND** does not present it as an error

### Requirement: Approximate playtime is presented as approximate

Where a playtime or session end time was reconstructed rather than observed, the interface SHALL present it as approximate rather than exact, so that an operator is never shown a reconstructed figure indistinguishable from a measured one.

#### Scenario: A session's end time was reconstructed

- **WHEN** a session whose end time was reconstructed is displayed
- **THEN** it is marked as approximate
- **AND** the reason its end time was reconstructed is available

#### Scenario: A total includes reconstructed sessions

- **WHEN** a player's total playtime includes one or more reconstructed sessions
- **THEN** the total is presented as approximate

### Requirement: The recorded period is visible in the roster

The interface SHALL make visible the date from which player history has been recorded, so that an operator whose server predates player history does not read its absence as data loss.

#### Scenario: The roster is viewed on an installation that predates recording

- **WHEN** the players section is opened
- **THEN** the date from which player history has been recorded is shown
