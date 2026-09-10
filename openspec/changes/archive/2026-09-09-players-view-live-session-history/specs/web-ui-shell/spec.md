## MODIFIED Requirements

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

#### Scenario: A displayed session ends while it is open

- **WHEN** a player whose session history is being displayed has their open session closed by the server, whether through a moderation action or an observed departure
- **THEN** the displayed session history reflects the closed session — its duration and how it ended — without the operator reloading or re-selecting the player

#### Scenario: No players have been observed

- **WHEN** the players section is opened and no players have been observed
- **THEN** the interface explains that no player history has been recorded yet
- **AND** does not present it as an error

### Requirement: Moderation actions are available from the player roster

The interface SHALL offer kick, ban, unban, and operator-rights actions on a player's entry in the roster, so that acting on a player happens where that player is already shown.

#### Scenario: A player is selected

- **WHEN** a player's roster entry is opened
- **THEN** the actions available for that player are presented
- **AND** each player's current access state is shown with their history

#### Scenario: A player is not currently online

- **WHEN** an offline player's entry is opened
- **THEN** kick is presented as unavailable
- **AND** ban, unban, and operator-rights actions remain available

#### Scenario: The server is not running

- **WHEN** the roster is opened while the managed server is not running
- **THEN** kick is presented as unavailable
- **AND** the durable actions remain available

#### Scenario: An action is applied

- **WHEN** a moderation action completes
- **THEN** the player's entry reflects the new state without the operator reloading
- **AND** the player's displayed session history and roster totals reflect the new state without the operator reloading

#### Scenario: An action closes the player's session after it completes

- **WHEN** a moderation action closes the player's open session some time after the action itself completes
- **THEN** the displayed session history reflects the closed session once the server reports it, without the operator reloading

#### Scenario: An action is refused

- **WHEN** a moderation action is refused
- **THEN** the reason is presented with the player it concerns
- **AND** the presented state continues to reflect what the server reports
