## ADDED Requirements

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
