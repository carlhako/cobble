## MODIFIED Requirements

### Requirement: A backup captures world state and cobble state as whole directories

A backup SHALL capture the Bedrock mutable-state directory and cobble's own state directory in their entirety, rather than an enumerated list of files, so that files introduced later are included without the backup mechanism being changed. Cobble's state directory holds its durable records, including the player history and roster database; the database SHALL be brought to a self-consistent form before it is captured so that a restored copy is usable without recovery.

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

#### Scenario: The state database is captured while cobble is running

- **WHEN** a backup is captured and cobble has an open player history and roster database
- **THEN** the database is flushed to a self-consistent form before it is added to the archive
- **AND** the captured copy can be opened without a recovery step after a restore

#### Scenario: The state database cannot be made consistent

- **WHEN** the state database cannot be brought to a self-consistent form
- **THEN** the backup fails rather than producing an archive that cannot be relied upon

## ADDED Requirements

### Requirement: A held backup can be retrieved as a single file

Cobble SHALL allow an operator to retrieve a held backup as a single file, so that a copy can be kept off the host or inspected elsewhere. The retrieved file SHALL be the captured archive as held, self-describing without any accompanying file. The identifier used to select the backup SHALL be validated against the set of held backups so that no file outside the backup destination can be retrieved.

#### Scenario: An operator retrieves a held backup

- **WHEN** an operator requests a held backup by its identifier
- **THEN** the backup archive is returned as a single downloadable file
- **AND** the file is named so that it is recognisable as that backup

#### Scenario: The requested backup does not exist

- **WHEN** a retrieval names an identifier that is not a held backup
- **THEN** the request is refused
- **AND** no file is returned

#### Scenario: The identifier attempts to escape the backup destination

- **WHEN** a retrieval names an identifier that resolves outside the backup destination
- **THEN** the request is refused
- **AND** no file is returned

#### Scenario: A backup that failed verification is retrieved

- **WHEN** an operator requests a held backup that is recorded as not restorable
- **THEN** the archive is still returned for inspection
