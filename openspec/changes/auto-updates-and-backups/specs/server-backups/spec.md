## Purpose

Capturing the Bedrock world and cobble's own durable state to the configured backup destination — on a schedule, before an update, and on operator request — and restoring a capture over the live installation so that a lost or damaged world is recoverable.

## ADDED Requirements

### Requirement: A backup captures world state and cobble state as whole directories

A backup SHALL capture the Bedrock mutable-state directory and cobble's own state directory in their entirety, rather than an enumerated list of files, so that files introduced later are included without the backup mechanism being changed.

#### Scenario: A backup is captured

- **WHEN** a backup is captured
- **THEN** it contains the Bedrock mutable-state directory and cobble's state directory in full

#### Scenario: New files appear in a captured directory

- **WHEN** a file that did not previously exist is added to either captured directory
- **THEN** subsequent backups include it
- **AND** no configuration change is required for it to be included

#### Scenario: A backup records what it contains

- **WHEN** a backup is captured
- **THEN** it records the time of capture, the Bedrock version installed at that time, and whether the preceding shutdown was clean

### Requirement: Backups are captured with the server stopped

Because the world is written continuously while the server runs, cobble SHALL stop the server before capturing a backup and SHALL return it to its previous run state afterwards.

#### Scenario: Backup while the server is running

- **WHEN** a backup is captured and the server is running
- **THEN** the server is stopped using the clean shutdown behavior before the capture begins
- **AND** the server is started again after the capture completes

#### Scenario: Backup while the server is stopped

- **WHEN** a backup is captured and the server is not running
- **THEN** the capture proceeds without starting the server
- **AND** the server is not started afterwards

#### Scenario: Shutdown for a backup is unclean

- **WHEN** the shutdown taken for a backup is recorded as unclean
- **THEN** the resulting backup records that its preceding shutdown was unclean

### Requirement: Backups are captured on a recurring schedule

Cobble SHALL capture a backup on a recurring schedule. The schedule SHALL be configurable and SHALL be capable of being disabled.

#### Scenario: The scheduled time arrives

- **WHEN** the scheduled time is reached and the backup schedule is enabled
- **THEN** a backup is captured

#### Scenario: The next scheduled run is observable

- **WHEN** the backup schedule is enabled
- **THEN** the time of the next scheduled backup is reported

#### Scenario: A scheduled backup and a scheduled update coincide

- **WHEN** a scheduled backup and a scheduled update check fall in the same window
- **THEN** they are performed as a single ordered sequence with the backup first
- **AND** the server is not stopped more than once for the pair

### Requirement: A backup can be requested on demand

Cobble SHALL allow an operator to capture a backup immediately.

#### Scenario: Operator requests a backup

- **WHEN** an operator requests a backup
- **THEN** a backup is captured using the same behavior as a scheduled capture

#### Scenario: Request made while a backup or restore is in progress

- **WHEN** a backup is requested and a backup or restore is already in progress
- **THEN** no second operation begins
- **AND** the request fails with an error identifying the operation in progress

### Requirement: An incomplete backup is never offered as restorable

Cobble SHALL verify a captured backup before treating it as usable, and SHALL NOT present an interrupted or unverifiable capture as available for restore.

#### Scenario: Capture is interrupted

- **WHEN** a backup capture is interrupted before completion
- **THEN** the incomplete capture is not listed as restorable
- **AND** previously captured backups remain intact

#### Scenario: Capture fails verification

- **WHEN** a captured backup does not verify
- **THEN** it is not listed as restorable
- **AND** the failure is recorded and surfaced

### Requirement: Backups are retained according to a policy

Cobble SHALL prune old backups according to a configurable retention policy, and SHALL NOT prune the most recent usable backup.

#### Scenario: Retention limit is exceeded

- **WHEN** the number of retained backups exceeds the configured retention
- **THEN** the oldest backups beyond the limit are removed

#### Scenario: The most recent backup is protected

- **WHEN** pruning is performed
- **THEN** the most recent usable backup is not removed

### Requirement: A failed backup is surfaced and does not disable the schedule

When a backup cannot be written, cobble SHALL record and surface the failure as an unhealthy condition and SHALL leave the schedule enabled so that later attempts are made.

#### Scenario: The destination cannot be written

- **WHEN** a scheduled backup cannot be written because the destination is unavailable, full, or not writable
- **THEN** the failure is recorded and surfaced as an unhealthy condition
- **AND** the server continues running

#### Scenario: A later scheduled run still occurs

- **WHEN** a scheduled backup has failed
- **THEN** the next scheduled backup is still attempted

#### Scenario: Failures repeat

- **WHEN** scheduled backups fail repeatedly
- **THEN** the schedule remains enabled
- **AND** the unhealthy condition remains surfaced

### Requirement: Captured backups are listed

Cobble SHALL report the backups it holds, so that an operator can see what is recoverable.

#### Scenario: Backups are listed

- **WHEN** the list of backups is requested
- **THEN** each backup is reported with its capture time, the Bedrock version recorded at capture, its size, and whether it is restorable

#### Scenario: No backups exist

- **WHEN** the list of backups is requested and none have been captured
- **THEN** an empty list is returned
- **AND** no error is raised

### Requirement: A backup can be restored over the live installation

Cobble SHALL restore a captured backup on operator request, replacing the current world and cobble state, and SHALL capture the state being replaced before overwriting it.

#### Scenario: Restore is performed

- **WHEN** an operator restores a captured backup
- **THEN** the server is stopped using the clean shutdown behavior
- **AND** the state being replaced is itself captured first
- **AND** the contents of the selected backup are put in place
- **AND** the server is started again

#### Scenario: Restore is refused while the server cannot be stopped cleanly

- **WHEN** a restore is requested and the server cannot be stopped cleanly
- **THEN** the existing state is not replaced
- **AND** the failure is reported

#### Scenario: Backup predates the installed server version

- **WHEN** a restore is requested for a backup whose recorded version is older than the installed version
- **THEN** the operator is warned that the world was captured under an older server version before the restore proceeds

#### Scenario: Restore fails

- **WHEN** a restore fails partway through
- **THEN** the failure is recorded and surfaced
- **AND** the capture taken of the replaced state remains available
