## ADDED Requirements

### Requirement: Version and update state are presented in the interface

The web interface SHALL present the installed Bedrock version, whether a newer version is available, when updates were last checked and applied, and when the next scheduled check will occur.

#### Scenario: A newer version is available

- **WHEN** a newer Bedrock version is available
- **THEN** the interface shows the installed version and the available version
- **AND** it indicates that an update is pending

#### Scenario: The server is current

- **WHEN** no newer version is available
- **THEN** the interface reports the installation as up to date

#### Scenario: Operator requests an update check

- **WHEN** an operator requests an update check from the interface
- **THEN** the check is performed
- **AND** the result is reflected without the operator refreshing

### Requirement: A failed update is surfaced with its diagnostics

The web interface SHALL alert the operator when an update has failed, and SHALL present the version attempted, the step at which it failed, and the server output captured during the attempt, without requiring access to the host's system logs.

#### Scenario: An update has failed

- **WHEN** the most recent update failed and was rolled back
- **THEN** the interface presents an alert stating that the update failed and was rolled back
- **AND** the version attempted, the failing step, and the captured output are available from that alert

#### Scenario: A version is not being retried

- **WHEN** the available version is one that previously failed an update
- **THEN** the interface indicates that it will not be retried automatically
- **AND** an operator can clear that record from the interface

#### Scenario: Rollback could not restore service

- **WHEN** a rollback failed to restore a running server
- **THEN** the interface presents this as requiring operator intervention

### Requirement: Backup and restore are available from the interface

The web interface SHALL list the backups cobble holds, allow an operator to capture a backup, and allow an operator to restore one.

#### Scenario: Backups are listed

- **WHEN** an operator views the backups section
- **THEN** each backup is listed with its capture time, recorded server version, and size

#### Scenario: Operator captures a backup

- **WHEN** an operator requests a backup from the interface
- **THEN** the backup is captured
- **AND** progress and the outcome are reflected without the operator refreshing

#### Scenario: Operator restores a backup

- **WHEN** an operator selects a backup to restore
- **THEN** the interface requires an explicit confirmation that identifies the backup and states that current state will be replaced
- **AND** the restore is performed only after that confirmation

#### Scenario: Backups are failing

- **WHEN** backups are failing because the destination cannot be written
- **THEN** the interface presents this as an unhealthy condition with the reason

### Requirement: Maintenance progress is reflected without operator action

The web interface SHALL indicate when an update, backup, or restore is in progress, show which step it has reached, and reflect its completion without the operator refreshing or re-navigating.

#### Scenario: A maintenance operation is in progress

- **WHEN** an update, backup, or restore is in progress
- **THEN** the interface indicates the operation and the step it has reached
- **AND** lifecycle actions that conflict with it are not offered

#### Scenario: A maintenance operation completes

- **WHEN** the operation completes
- **THEN** the interface reflects the new state without operator action

#### Scenario: The interface is opened during a maintenance operation

- **WHEN** an operator opens the interface while a maintenance operation is already in progress
- **THEN** the operation and its current step are shown
