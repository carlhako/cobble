## ADDED Requirements

### Requirement: Maintenance operations exclude conflicting lifecycle actions

While cobble is performing a multi-step maintenance operation that owns the server's lifecycle — an update, a backup, or a restore — it SHALL reject lifecycle requests that would conflict with it, rather than interleaving them.

#### Scenario: Lifecycle action requested during maintenance

- **WHEN** a start, stop, or restart is requested while a maintenance operation is in progress
- **THEN** the request fails with an error identifying the maintenance operation in progress
- **AND** the maintenance operation continues unaffected

#### Scenario: Maintenance requested during a lifecycle transition

- **WHEN** a maintenance operation is requested while a lifecycle transition is already in progress
- **THEN** the maintenance operation does not begin
- **AND** the request fails with an error identifying the transition in progress

#### Scenario: Maintenance completes

- **WHEN** a maintenance operation completes or is abandoned
- **THEN** lifecycle actions are accepted again

#### Scenario: Cobble terminates during maintenance

- **WHEN** cobble receives a termination signal while a maintenance operation is in progress
- **THEN** the managed server is stopped using the clean shutdown behavior before cobble exits
- **AND** the interrupted operation is recorded so that its outcome is not reported as successful

## MODIFIED Requirements

### Requirement: Crash recovery does not loop indefinitely

Cobble SHALL be able to restart a crashed server automatically, and SHALL stop attempting restarts when failures repeat, leaving the failure visible rather than retrying forever. Automatic restart SHALL be suspended while a maintenance operation is in progress, so that the maintenance operation alone decides when the server is started.

#### Scenario: Automatic restart after a crash

- **WHEN** the server crashes and automatic restart is enabled
- **THEN** cobble attempts to start the server again

#### Scenario: Repeated crashes halt recovery

- **WHEN** the server crashes repeatedly beyond the configured failure threshold
- **THEN** cobble stops attempting automatic restarts
- **AND** the run state reports that recovery was abandoned
- **AND** an operator can still request a start manually

#### Scenario: Server exits during a maintenance operation

- **WHEN** the server process exits while a maintenance operation is in progress
- **THEN** automatic restart does not occur
- **AND** the exit is reported to the maintenance operation to act on

#### Scenario: Automatic restart resumes after maintenance

- **WHEN** a maintenance operation completes or is abandoned
- **THEN** automatic crash restart applies again to subsequent crashes
