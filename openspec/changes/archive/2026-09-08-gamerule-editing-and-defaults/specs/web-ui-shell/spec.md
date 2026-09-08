## ADDED Requirements

### Requirement: Gamerules are editable from the interface

The interface SHALL present the active world's gamerules with their current values, typed according to each rule — a checkbox for a boolean, a bounded number for an integer, a choice for an enumerated rule — and SHALL apply a change without requiring the operator to restart the server. A rule cobble has no type information for SHALL be presented as editable text and SHALL NOT be hidden.

#### Scenario: The gamerules are viewed

- **WHEN** the operator opens the gamerules section and the server is running
- **THEN** every gamerule reported by the server is listed with its current value, presented according to its type

#### Scenario: A rule is changed

- **WHEN** the operator changes a gamerule and the server is running
- **THEN** the change is applied to the running server
- **AND** the value shown afterwards is the value read back from the server
- **AND** no restart is offered or required

#### Scenario: A change is rejected

- **WHEN** a submitted gamerule value is refused
- **THEN** the reason is shown against that rule
- **AND** the displayed value returns to the value in effect

#### Scenario: A rule of unknown type

- **WHEN** the server reports a gamerule the interface has no type information for
- **THEN** it is shown as editable text and marked as unrecognised

### Requirement: The gamerule presentation distinguishes live values from recorded ones

Because gamerules can only be read from a running server, the interface SHALL make clear whether the values shown are live or were recorded earlier, and SHALL never present a recorded value as current.

#### Scenario: The server is stopped

- **WHEN** the operator opens the gamerules section and the server is not running
- **THEN** the last recorded values for the active world are shown, marked as recorded, with the time they were taken

#### Scenario: A world that has never been read

- **WHEN** the active world has no recorded gamerules and the server is not running
- **THEN** the section states that the rules have not been read rather than showing any values

#### Scenario: A change made while stopped

- **WHEN** the operator changes a gamerule while the server is not running
- **THEN** the interface states that the change will be applied when the server next starts

### Requirement: Gamerule changes made outside the interface are surfaced

The interface SHALL show the operator when cobble has adopted a gamerule changed in game, re-applied recorded rules after a restore, or applied preferred defaults to a new world, and SHALL allow the operator to acknowledge it.

#### Scenario: A rule was changed in game

- **WHEN** cobble has adopted a gamerule changed outside the interface
- **THEN** the interface reports which rule changed and the value cobble has saved

#### Scenario: Rules were repaired after a restore

- **WHEN** cobble has re-applied recorded gamerules following a restore
- **THEN** the interface reports which rules were re-applied and why

#### Scenario: The report is acknowledged

- **WHEN** the operator acknowledges the report
- **THEN** it is dismissed and does not reappear
- **AND** the gamerule values are unchanged

### Requirement: Preferred gamerule defaults are editable from the interface

The interface SHALL let the operator maintain a set of preferred gamerule values to be applied to any world cobble observes for the first time, and SHALL make clear that they do not affect worlds already recorded.

#### Scenario: Defaults are edited

- **WHEN** the operator sets a preferred default for a gamerule
- **THEN** it is saved
- **AND** the interface states that it applies only to worlds cobble has not seen before

#### Scenario: Defaults are distinguished from the active world's values

- **WHEN** the operator views the preferred defaults
- **THEN** they are presented separately from the active world's current gamerules

### Requirement: Gamerule editing is unavailable during maintenance

The interface SHALL prevent gamerule changes while an update, backup, or restore is in progress, and SHALL continue to present the current values.

#### Scenario: Maintenance begins while the section is open

- **WHEN** a maintenance operation starts while the operator has the gamerules section open
- **THEN** editing becomes unavailable with the operation in progress named
- **AND** the values remain visible

#### Scenario: Maintenance completes

- **WHEN** the maintenance operation finishes
- **THEN** editing becomes available again without the operator reloading the interface
