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
