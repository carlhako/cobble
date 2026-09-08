## Purpose

The world's gamerules as cobble sees them: how the live set is read from and written to a running server, how cobble keeps a per-world record of it, how a divergence between the two is classified as an operator's change to adopt or a restore's loss to repair, and how an operator's preferred defaults reach a world for the first time.

## Requirements

### Requirement: The live gamerule set is readable

Cobble SHALL report the gamerules in effect on the running server, each with its name and current value.

#### Scenario: Rules are reported while the server is running

- **WHEN** the gamerule set is requested and the server is running
- **THEN** every gamerule the server reports is returned with its current value

#### Scenario: Reading does not disturb the console

- **WHEN** cobble reads the gamerule set
- **THEN** neither the request nor the server's reply appears in the console stream delivered to clients

#### Scenario: Reading fails without leaving the set unknown

- **WHEN** a read of the gamerule set cannot be completed
- **THEN** the failure is reported
- **AND** the most recently recorded set remains available, marked as not current

### Requirement: A gamerule is writable and takes effect immediately

Cobble SHALL apply a submitted gamerule value to the running server without requiring a restart or a world reload.

#### Scenario: A rule is changed

- **WHEN** an operator submits a new value for a gamerule and the server is running
- **THEN** the value is applied to the running server
- **AND** no restart is required for it to take effect

#### Scenario: A rule is changed while the server is stopped

- **WHEN** an operator submits a new value for a gamerule and the server is not running
- **THEN** the value is recorded as the intended value for that world
- **AND** it is applied when the server next starts on that world

### Requirement: A write is confirmed by re-reading the value

Because the server's acknowledgement of a gamerule change can itself be suppressed by a gamerule, cobble SHALL determine the outcome of a write by reading the value back rather than by interpreting the acknowledgement.

#### Scenario: Outcome reflects the value actually in effect

- **WHEN** a gamerule write completes
- **THEN** the value reported to the operator is one cobble has read back from the server

#### Scenario: Acknowledgement is suppressed

- **WHEN** a gamerule write is made while the server is configured to suppress command acknowledgements
- **THEN** the write is still reported as succeeded or failed correctly

### Requirement: Submitted values are validated

Cobble SHALL reject a gamerule value that does not match the rule's type or permitted range, and SHALL surface a rejection made by the server.

#### Scenario: Value of the wrong type

- **WHEN** a value that does not match the rule's type is submitted
- **THEN** the write is refused with a reason naming the rule
- **AND** nothing is sent to the server

#### Scenario: Value outside the permitted range

- **WHEN** a numeric value outside the rule's permitted range is submitted
- **THEN** the write is refused with a reason stating the permitted range

#### Scenario: The server rejects a value cobble accepted

- **WHEN** the server refuses a submitted value
- **THEN** the server's reason is surfaced to the operator
- **AND** the recorded value for that rule is left unchanged

### Requirement: Rules cobble does not recognise are reported, not dropped

Because the set of gamerules changes between Bedrock versions, cobble SHALL report a rule it has no type information for rather than omitting it.

#### Scenario: An unrecognised rule is present

- **WHEN** the server reports a gamerule cobble has no type information for
- **THEN** that rule and its value are reported
- **AND** it is distinguishable from rules cobble recognises

### Requirement: The gamerule set is recorded per world

Because gamerules belong to a world and not to the server, cobble SHALL keep a record of the gamerule set for each world it has observed, identified by that world's name.

#### Scenario: Each world keeps its own record

- **WHEN** cobble has observed gamerules on more than one world
- **THEN** each world's record is kept separately
- **AND** changing the active world does not alter another world's record

#### Scenario: The record is sampled at start and before stop

- **WHEN** the server becomes ready, and again immediately before cobble stops it
- **THEN** the gamerule set in effect is recorded against the active world

### Requirement: The recorded set is reported when the server is stopped

Cobble SHALL report a stopped world's gamerules from its record, so that the operator can see them without starting the server.

#### Scenario: Rules are shown while stopped

- **WHEN** the gamerule set is requested for a world with a record and the server is not running
- **THEN** the recorded set is returned
- **AND** it is marked as recorded rather than live, with the time it was taken

#### Scenario: A world cobble has never run

- **WHEN** the gamerule set is requested for a world cobble has no record of
- **THEN** the response states that the rules have not been read
- **AND** no values are guessed or presented as that world's

### Requirement: A divergence from the record is adopted and reported

When the live gamerule set differs from cobble's record and cobble did not cause the difference, the change was made by an operator in game and SHALL be treated as intended: cobble SHALL adopt the live value as the new record and report that it did so.

#### Scenario: A rule was changed in game

- **WHEN** the live value of a rule differs from the record and cobble did not cause it
- **THEN** the live value replaces the recorded one
- **AND** the change is reported to the operator, naming the rule and its new value

#### Scenario: Adoption never reverts the change

- **WHEN** cobble adopts a divergence
- **THEN** the value on the running server is left as the operator set it

#### Scenario: No divergence

- **WHEN** the live gamerule set matches the record
- **THEN** nothing is reported

### Requirement: A divergence following a restore is repaired

Because restoring a backup reverts a world's gamerules along with the rest of the world, and that is indistinguishable from an operator's change by value alone, cobble SHALL treat a divergence observed on the first start after a restore as a loss to repair rather than a change to adopt.

#### Scenario: Rules are put back after a restore

- **WHEN** the server starts for the first time after a restore and the live rules differ from the record
- **THEN** the recorded values are re-applied to the running server
- **AND** the repair is reported to the operator, naming the rules it re-applied

#### Scenario: Later starts adopt again

- **WHEN** the server starts again after the start that followed a restore
- **THEN** a divergence is adopted rather than repaired

### Requirement: Preferred defaults are applied to a world seen for the first time

Because a per-world record cannot carry a preference into a world that did not previously exist, cobble SHALL let the operator keep a set of preferred gamerule values and SHALL apply them to a world the first time it observes it.

#### Scenario: A new world receives the defaults

- **WHEN** the server becomes ready on a world cobble has no record of and preferred defaults are set
- **THEN** those defaults are applied to the running server
- **AND** the resulting set becomes that world's record
- **AND** the application is reported to the operator

#### Scenario: Defaults do not reach an existing world

- **WHEN** the server becomes ready on a world cobble already has a record of
- **THEN** the preferred defaults are not applied
- **AND** that world's own record governs

#### Scenario: No defaults are set

- **WHEN** the server becomes ready on a world cobble has no record of and no preferred defaults are set
- **THEN** the live set is recorded as that world's baseline and nothing is changed

### Requirement: Gamerule operations never disrupt the server

Reading, writing, recording, and reconciling gamerules SHALL be incapable of stopping, delaying, or crashing the managed server.

#### Scenario: A gamerule operation fails

- **WHEN** any gamerule read, write, or record operation raises an error
- **THEN** the error is logged and surfaced
- **AND** the Bedrock server continues running unaffected

#### Scenario: The server does not answer a query

- **WHEN** the server produces no reply to a gamerule query within a bounded time
- **THEN** the query is abandoned
- **AND** the server and the console remain unaffected

### Requirement: Gamerule writes are refused during maintenance

Cobble SHALL refuse gamerule writes while an update, backup, or restore is in progress, and SHALL keep reads available.

#### Scenario: A write during maintenance

- **WHEN** a gamerule write is submitted while a maintenance operation is in progress
- **THEN** the write is refused with a reason naming the operation in progress

#### Scenario: A read during maintenance

- **WHEN** the gamerule set is requested while a maintenance operation is in progress
- **THEN** the request succeeds
