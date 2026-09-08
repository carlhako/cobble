## ADDED Requirements

### Requirement: The available server version is reported alongside the installed one

Cobble SHALL report the most recently observed available Bedrock version together with the installed version, so that an operator can see whether the server is behind.

#### Scenario: A newer version is known to be available

- **WHEN** a version check has found a version newer than the installed one
- **THEN** the status reports both the installed version and the available version

#### Scenario: The installed version is current

- **WHEN** a version check has found no newer version
- **THEN** the status reports that the installed version is current

#### Scenario: No check has succeeded

- **WHEN** no version check has yet succeeded
- **THEN** the status reports that the available version is unknown
- **AND** no error is raised

### Requirement: Update activity is reported

Cobble SHALL report when updates were last checked and last applied, the outcome of the most recent update, and when the next scheduled check will occur.

#### Scenario: Update state is queried

- **WHEN** status is requested
- **THEN** the time of the last update check, the outcome of the most recent update, and the next scheduled check are reported

#### Scenario: An update failed

- **WHEN** the most recent update failed
- **THEN** the status reports the failure, the version that was attempted, and the step at which it failed
- **AND** the output captured during the failed attempt is retrievable

#### Scenario: A version is being skipped

- **WHEN** the available version is one that previously failed an update
- **THEN** the status reports that this version is not being retried automatically

### Requirement: Backup activity is reported

Cobble SHALL report when a backup was last captured, whether it succeeded, when the next scheduled backup will occur, and the backups currently held.

#### Scenario: Backup state is queried

- **WHEN** status is requested
- **THEN** the time and outcome of the last backup and the next scheduled backup are reported

#### Scenario: Backups cannot be written

- **WHEN** backups are failing because the destination cannot be written
- **THEN** the status reports an unhealthy backup condition with the reason

#### Scenario: No backups have been captured

- **WHEN** status is requested and no backup has been captured
- **THEN** this is reported without error

### Requirement: Maintenance activity is reported separately from run state

Because an update or restore moves the server through several run states, cobble SHALL report whether a maintenance operation is in progress as a value distinct from the run state.

#### Scenario: An update is in progress

- **WHEN** an update is in progress
- **THEN** the status reports that an update is in progress
- **AND** the run state continues to report what the server process is doing

#### Scenario: A restore is in progress

- **WHEN** a restore is in progress
- **THEN** the status reports that a restore is in progress

#### Scenario: No maintenance is in progress

- **WHEN** no maintenance operation is in progress
- **THEN** the status reports no maintenance activity

#### Scenario: Maintenance progress is pushed to clients

- **WHEN** a maintenance operation begins, advances between steps, or ends
- **THEN** connected clients are notified without polling
