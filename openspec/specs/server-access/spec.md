## Purpose

Who may join this server and what they may do once in — the allowlist and whether it is being enforced, operator permissions, cobble's durable record of who was deliberately excluded, and the composite actions that keep those three consistent with one another and with the running server.

## Requirements

### Requirement: The allowlist is readable

Cobble SHALL report the set of players permitted to join, whether or not the managed server is running, so that an operator can see who may join without shell access to the host.

#### Scenario: The allowlist is requested

- **WHEN** the allowlist is requested
- **THEN** every entry is reported with the name it carries
- **AND** the stable identifier is reported for each entry that has one

#### Scenario: An entry has no stable identifier

- **WHEN** an entry names a player cobble has no stable identifier for
- **THEN** the entry is reported with its name and no identifier
- **AND** the entry is distinguishable from one that has an identifier

#### Scenario: The allowlist is empty

- **WHEN** the stored allowlist records no players
- **THEN** an empty allowlist is reported
- **AND** no error is raised

#### Scenario: The stored allowlist records emptiness as an absent value

- **WHEN** the stored allowlist represents an empty list as a null value rather than an empty one
- **THEN** an empty allowlist is reported
- **AND** no error is raised

#### Scenario: The stored allowlist cannot be read

- **WHEN** the stored allowlist is absent or cannot be interpreted
- **THEN** the condition is reported
- **AND** no error is raised

#### Scenario: The server is not running

- **WHEN** the allowlist is requested while the managed server is not running
- **THEN** the allowlist is reported from durable state

### Requirement: The allowlist is writable

Cobble SHALL accept additions to and removals from the allowlist and persist them, applying them to a running server without a restart.

#### Scenario: A player is added

- **WHEN** a player is added to the allowlist
- **THEN** the addition is persisted
- **AND** a subsequent read reports the player as permitted

#### Scenario: A player is added while the server runs

- **WHEN** a player is added while the managed server is running
- **THEN** the running server is instructed to reload the allowlist
- **AND** the addition takes effect without a restart

#### Scenario: A player is added while the server is stopped

- **WHEN** a player is added while the managed server is not running
- **THEN** the addition is persisted
- **AND** it takes effect when the server next starts

#### Scenario: A player known to cobble is added

- **WHEN** a player cobble holds a stable identifier for is added
- **THEN** the entry is persisted with both that identifier and the player's current name

#### Scenario: A player unknown to cobble is added

- **WHEN** a player cobble holds no stable identifier for is added by name
- **THEN** the entry is persisted with the name alone
- **AND** the entry is reported as having no identifier

#### Scenario: A name containing spaces is added

- **WHEN** a player whose name contains spaces is added
- **THEN** the entry is persisted with that name intact

#### Scenario: The last entry is removed

- **WHEN** the only remaining entry is removed from the allowlist
- **THEN** a subsequent read reports an empty allowlist
- **AND** no error is raised

### Requirement: Writing the allowlist preserves what cobble does not recognise

Cobble SHALL preserve stored allowlist content it has no meaning for, so that an entry written by the Bedrock server or by hand survives a write by cobble.

#### Scenario: An entry carries an unrecognised field

- **WHEN** the allowlist is written and an existing entry carries a field cobble does not recognise
- **THEN** that field is preserved with its value

#### Scenario: An entry cobble did not create is left alone

- **WHEN** the allowlist is written and an existing entry is not the subject of the change
- **THEN** that entry is unchanged

### Requirement: Allowlist enforcement state is reported and settable

Because the Bedrock server can be told to enforce the allowlist without that instruction being recorded in its configuration file, cobble SHALL report whether the allowlist is being enforced right now, distinctly from what the configuration file says.

#### Scenario: Enforcement state is requested

- **WHEN** the enforcement state is requested
- **THEN** whether the running server is enforcing the allowlist is reported
- **AND** what the saved configuration says is reported

#### Scenario: The two disagree

- **WHEN** the running server's enforcement differs from the saved configuration
- **THEN** both values are reported
- **AND** the disagreement is reported

#### Scenario: Enforcement is turned on

- **WHEN** allowlist enforcement is turned on
- **THEN** the running server begins enforcing it
- **AND** the saved configuration records it as enabled

#### Scenario: Enforcement is turned off

- **WHEN** allowlist enforcement is turned off
- **THEN** the running server stops enforcing it
- **AND** the saved configuration records it as disabled

#### Scenario: The server starts

- **WHEN** the managed server becomes ready
- **THEN** the enforcement state recorded in the saved configuration is applied to it

#### Scenario: Enforcement is changed outside cobble

- **WHEN** allowlist enforcement is changed by any means other than cobble while the server is running
- **THEN** the reported enforcement state reflects the change

### Requirement: Turning on enforcement reports who it would exclude

Because enabling the allowlist excludes every player not on it, cobble SHALL report which players who have played on this server would be excluded, before enforcement is enabled.

#### Scenario: Enabling enforcement would exclude known players

- **WHEN** enabling enforcement is requested and players in cobble's roster are absent from the allowlist
- **THEN** those players are reported by name before the change is applied
- **AND** the change is not applied until it is confirmed

#### Scenario: Enabling enforcement would exclude nobody known

- **WHEN** enabling enforcement is requested and every player in cobble's roster is on the allowlist
- **THEN** no players are reported as excluded

#### Scenario: Excluded players are carried onto the list

- **WHEN** enabling enforcement is confirmed together with a request to permit the players it would exclude
- **THEN** those players are added to the allowlist
- **AND** enforcement is enabled

### Requirement: Operator permissions are readable and writable

Cobble SHALL report and change the permission level held by each player, identifying each by the stable identifier the permission record uses and by the name cobble knows for it.

#### Scenario: Permissions are requested

- **WHEN** the permission records are requested
- **THEN** every record is reported with its stable identifier and permission level
- **AND** the name cobble knows for that identifier is reported alongside it where one is known

#### Scenario: A record names an identifier cobble has never seen

- **WHEN** a permission record carries an identifier absent from cobble's roster
- **THEN** the record is reported with its identifier and no name

#### Scenario: A permission level is changed

- **WHEN** a player's permission level is changed to a level the server defines
- **THEN** the change is persisted
- **AND** a subsequent read reports the new level

#### Scenario: A permission level is changed while the server runs

- **WHEN** a permission level is changed while the managed server is running
- **THEN** the running server is instructed to reload permissions
- **AND** the change takes effect without a restart

#### Scenario: A permission level is changed for an offline player

- **WHEN** a permission level is changed for a player who is not currently connected
- **THEN** the change is persisted and takes effect for that player

#### Scenario: An unrecognised permission level is submitted

- **WHEN** a permission level the server does not define is submitted
- **THEN** the change is refused with a reason
- **AND** nothing is persisted

#### Scenario: The outcome is confirmed by reading

- **WHEN** a permission change has been applied
- **THEN** the reported result is the state read back after the change
- **AND** the result does not depend on the server having acknowledged the change

### Requirement: A ban is recorded durably and distinctly from absence

Cobble SHALL keep its own record of every player it has banned, so that a deliberate exclusion is distinguishable from a player who was simply never permitted.

#### Scenario: A player is banned

- **WHEN** a player is banned
- **THEN** a record is kept of the player's stable identifier, the name they held at that time, the stated reason, and when it happened

#### Scenario: A banned player is reported

- **WHEN** a banned player is reported
- **THEN** the player is reported as banned
- **AND** the reason and the time of the ban are reported

#### Scenario: A player absent from the allowlist was never banned

- **WHEN** a player who has never been banned is absent from the allowlist
- **THEN** the player is not reported as banned

#### Scenario: A player renames after being banned

- **WHEN** a banned player's name changes
- **THEN** the ban still applies to that player
- **AND** the name recorded at the time of the ban remains available

### Requirement: Banning a player removes them and keeps them out

Because removing a player from the allowlist neither disconnects them nor has any effect while the allowlist is unenforced, cobble SHALL treat banning as a single action that achieves both, or reports which part it could not.

#### Scenario: An online player is banned

- **WHEN** a connected player is banned
- **THEN** the player is removed from the allowlist
- **AND** allowlist enforcement is in effect
- **AND** the player is disconnected from the server
- **AND** the ban is recorded

#### Scenario: An offline player is banned

- **WHEN** a player who is not connected is banned
- **THEN** the player is removed from the allowlist
- **AND** allowlist enforcement is in effect
- **AND** the ban is recorded

#### Scenario: A player is banned while enforcement is off

- **WHEN** a player is banned and the allowlist is not being enforced
- **THEN** enabling enforcement is part of the action
- **AND** the players that enabling it would exclude are reported before it is applied

#### Scenario: A player is banned while the server is stopped

- **WHEN** a player is banned while the managed server is not running
- **THEN** the durable parts of the ban are applied
- **AND** no disconnection is attempted
- **AND** the ban takes effect when the server next starts

#### Scenario: The disconnection cannot be confirmed

- **WHEN** a ban's disconnection step produces no observed departure within a bounded time
- **THEN** the ban is reported as recorded with the disconnection unconfirmed
- **AND** the durable parts of the ban remain in effect

### Requirement: A ban can be lifted

Cobble SHALL allow a recorded ban to be lifted, restoring the player's permission to join.

#### Scenario: A ban is lifted

- **WHEN** a banned player is unbanned
- **THEN** the player is added to the allowlist
- **AND** the player is no longer reported as banned

#### Scenario: Enforcement is left as it stands

- **WHEN** a ban is lifted and allowlist enforcement was enabled by an earlier ban
- **THEN** enforcement remains as it is
- **AND** the enforcement state is not changed as a side effect of lifting the ban

#### Scenario: Lifting a ban on a player with no identifier

- **WHEN** a ban is lifted for a player cobble holds no stable identifier for
- **THEN** the player is added to the allowlist by the name recorded at the time of the ban

### Requirement: A player can be disconnected without being banned

Cobble SHALL allow a connected player to be disconnected as an act with no durable effect, so that a temporary removal does not require excluding the player.

#### Scenario: A connected player is disconnected

- **WHEN** a connected player is kicked
- **THEN** the player is disconnected from the server
- **AND** the allowlist is unchanged
- **AND** no ban is recorded

#### Scenario: A reason is supplied

- **WHEN** a player is kicked with a stated reason
- **THEN** the reason is conveyed to the server

#### Scenario: The player is not connected

- **WHEN** a kick is requested for a player who is not connected
- **THEN** the request is refused with a reason
- **AND** nothing is sent to the server

#### Scenario: The server is not running

- **WHEN** a kick is requested while the managed server is not running
- **THEN** the request is refused with a reason

#### Scenario: The disconnection is observed

- **WHEN** a kicked player's departure is observed
- **THEN** the kick is reported as confirmed

#### Scenario: The disconnection is not observed

- **WHEN** no departure is observed for a kicked player within a bounded time
- **THEN** the kick is reported as unconfirmed
- **AND** the outcome is not reported as a failure

### Requirement: Access changes are visible to the operator

Cobble SHALL make the actions it takes on an operator's behalf visible, so that no change to who may join happens without a trace.

#### Scenario: A player is kicked or banned

- **WHEN** cobble disconnects a player on an operator's request
- **THEN** the command it issues appears in the console output stream

#### Scenario: Composite steps are reported

- **WHEN** a ban completes
- **THEN** each part of it that was carried out is reported

### Requirement: Access writes are refused during maintenance

Cobble SHALL refuse changes to the allowlist, permissions, and ban records while an update, backup, or restore is in progress, so that a write cannot race an operation that captures or replaces stored state.

#### Scenario: A change is requested during maintenance

- **WHEN** an access change is requested while an update, backup, or restore is in progress
- **THEN** the change is refused with a distinguishable reason
- **AND** nothing is persisted

#### Scenario: Reads remain available during maintenance

- **WHEN** the allowlist, permissions, or ban records are requested while maintenance is in progress
- **THEN** they are reported normally

#### Scenario: Maintenance completes

- **WHEN** maintenance completes
- **THEN** access changes are accepted again
