## Purpose

A durable, append-only record of every backup cobble has successfully captured, so an operator can see backup activity over time even after older archives have been pruned from the backup destination.

## Requirements

### Requirement: A successful backup is recorded in history

Cobble SHALL append a record to backup history whenever a backup is successfully captured and verified, regardless of what triggered it (scheduled, manual, or the mandatory pre-update backup).

#### Scenario: A scheduled backup succeeds

- **WHEN** a scheduled backup is captured and verified
- **THEN** a history record is appended noting the capture time, the Bedrock version recorded at capture, the archive size, and that it was scheduled

#### Scenario: A manual backup succeeds

- **WHEN** an operator-requested backup is captured and verified
- **THEN** a history record is appended noting that it was manually requested

#### Scenario: A pre-update backup succeeds

- **WHEN** the mandatory pre-update backup taken during an update is captured and verified
- **THEN** a history record is appended noting that it preceded an update

### Requirement: A failed backup attempt is not recorded in history

Backup history SHALL record successful captures only; a failed or unverifiable attempt SHALL NOT appear there.

#### Scenario: A backup fails to capture

- **WHEN** a backup capture fails or fails verification
- **THEN** no record is appended to backup history
- **AND** the failure remains visible through the existing backup-health surface

### Requirement: History persists independent of file retention

A backup history record SHALL remain readable after the backup archive it describes has been pruned by the retention policy, and SHALL indicate whether the archive is still held.

#### Scenario: A recorded backup is later pruned

- **WHEN** a backup described in history is later removed by retention pruning
- **THEN** its history record remains present
- **AND** the record indicates the archive is no longer held

#### Scenario: A recorded backup is still held

- **WHEN** a backup described in history has not been pruned
- **THEN** the record indicates the archive is still held

### Requirement: Backup history is listed to operators

Cobble SHALL report the full backup history on request, ordered newest first.

#### Scenario: History is requested

- **WHEN** backup history is requested
- **THEN** every recorded backup is returned, most recent first, with its capture time, trigger, recorded version, size, and whether it is still held

#### Scenario: No backups have ever been captured

- **WHEN** backup history is requested and none have been recorded
- **THEN** an empty list is returned
- **AND** no error is raised
