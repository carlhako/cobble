## ADDED Requirements

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

#### Scenario: An action is refused

- **WHEN** a moderation action is refused
- **THEN** the reason is presented with the player it concerns
- **AND** the presented state continues to reflect what the server reports

### Requirement: Banning names who else it would exclude

Because enabling the allowlist excludes every player not on it, the interface SHALL present who would be excluded before a ban that enables enforcement is applied.

#### Scenario: A ban would enable enforcement

- **WHEN** a ban is requested while allowlist enforcement is off
- **THEN** the interface presents that enforcement will be enabled
- **AND** it names the players who have played on this server and are not on the allowlist
- **AND** the ban is not applied until it is confirmed

#### Scenario: The excluded players are carried onto the list

- **WHEN** the operator chooses to permit the players the change would exclude
- **THEN** those players are added to the allowlist as part of the same action

#### Scenario: Enforcement is already on

- **WHEN** a ban is requested while enforcement is already in effect
- **THEN** no exclusion warning is presented

#### Scenario: A ban is confirmed

- **WHEN** a ban is confirmed
- **THEN** the parts of it that were carried out are presented afterwards

### Requirement: A ban is presented with its reason and time

The interface SHALL present a banned player's reason and ban time, and distinguish a banned player from one who is merely absent from the allowlist.

#### Scenario: A banned player is shown

- **WHEN** a banned player is presented
- **THEN** the reason and the time of the ban are shown

#### Scenario: A player was never banned

- **WHEN** a player absent from the allowlist has no ban record
- **THEN** they are not presented as banned

### Requirement: The allowlist and permissions are visible from the interface

The interface SHALL present the allowlist and the permission records, including entries with no counterpart in the roster, so that the presented list is never a partial view of itself.

#### Scenario: The allowlist is shown

- **WHEN** the allowlist is presented
- **THEN** every entry is shown
- **AND** entries naming players who have never played here are shown as such

#### Scenario: An entry has no stable identifier

- **WHEN** an allowlist entry has no stable identifier
- **THEN** it is presented as identified by name alone

#### Scenario: A permission record names an unknown identifier

- **WHEN** a permission record names an identifier absent from the roster
- **THEN** the record is presented with its identifier and no name

### Requirement: Allowlist enforcement state is presented distinctly from the saved setting

The interface SHALL present whether the allowlist is being enforced right now separately from what the saved configuration says, so that a divergence between them is visible rather than silent.

#### Scenario: The two agree

- **WHEN** the enforcement in effect matches the saved setting
- **THEN** the enforcement state is presented as a single settled value

#### Scenario: The two disagree

- **WHEN** the enforcement in effect differs from the saved setting
- **THEN** both are presented
- **AND** which one is in effect now is identified

#### Scenario: The state has not been observed

- **WHEN** cobble has not observed the running server's enforcement state
- **THEN** it is presented as unknown rather than as a value

### Requirement: Moderation is unavailable during maintenance

The interface SHALL present moderation actions as unavailable while an update, backup, or restore is in progress, so that a refusal is anticipated rather than encountered.

#### Scenario: Maintenance begins

- **WHEN** an update, backup, or restore begins
- **THEN** the moderation actions are presented as unavailable
- **AND** the reason is presented

#### Scenario: Maintenance completes

- **WHEN** maintenance completes
- **THEN** the actions become available again without the operator reloading

#### Scenario: Reading remains available

- **WHEN** maintenance is in progress
- **THEN** the roster, allowlist, permissions, and ban records remain readable
