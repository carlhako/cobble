## ADDED Requirements

### Requirement: Bedrock mutable state is stored separately from the versioned installation

Cobble SHALL store the Bedrock server's mutable state — the world and the operator-editable configuration files — in a location separate from the versioned installation directory, so that replacing the active version neither moves nor endangers it. That location SHALL be the unit of capture for backups.

#### Scenario: Active version is replaced

- **WHEN** the active Bedrock version changes
- **THEN** the world and the operator-editable configuration are unaffected
- **AND** they are not copied or moved as part of the change

#### Scenario: Mutable state is treated as a unit

- **WHEN** a consumer needs to capture the Bedrock server's mutable state
- **THEN** the mutable-state location is the unit of capture
- **AND** files added to it later are included without that consumer being changed

#### Scenario: The server reads and writes its state in place

- **WHEN** the Bedrock server runs
- **THEN** it reads its configuration from, and writes its world to, the separated mutable-state location
- **AND** it does so regardless of which version is active

### Requirement: An existing installation is migrated to the separated layout

Where an installation holds its world and configuration inside the versioned installation directory, cobble SHALL relocate them to the separated mutable-state location. The migration SHALL occur once, SHALL capture a verified backup before moving anything, and SHALL be safe to interrupt.

#### Scenario: An installation predating the separated layout is found

- **WHEN** cobble starts and finds the world inside the versioned installation directory
- **THEN** a verified backup is captured before anything is moved
- **AND** the world and operator-editable configuration are relocated to the mutable-state location
- **AND** the server is not running while they are moved

#### Scenario: Migration completes

- **WHEN** the migration completes
- **THEN** the server starts against the separated layout
- **AND** the migration is not performed again on subsequent starts

#### Scenario: Backup cannot be captured before migration

- **WHEN** a verified backup cannot be captured before the migration
- **THEN** nothing is moved
- **AND** the failure is reported

#### Scenario: Migration is interrupted

- **WHEN** a migration is interrupted before completion
- **THEN** no world data is lost
- **AND** a subsequent start completes the migration rather than restarting it from an inconsistent state

#### Scenario: Installation already uses the separated layout

- **WHEN** cobble starts and the installation already uses the separated layout
- **THEN** no migration is performed

## MODIFIED Requirements

### Requirement: Server installations are stored per version

Cobble SHALL store each Bedrock server installation in its own directory named for its version, and SHALL designate the active installation by an indirection that can be changed without moving files. A version's directory SHALL contain only the files supplied by the vendor, so that it can be replaced or removed without affecting the world or the operator's configuration.

#### Scenario: A version is installed

- **WHEN** a Bedrock server version is installed
- **THEN** its files are placed in a directory identified by that version
- **AND** existing version directories are left unmodified

#### Scenario: Active version is designated

- **WHEN** a version is made active
- **THEN** the active-installation indirection points at that version's directory
- **AND** the change does not require copying or moving installation files

#### Scenario: A version directory holds no mutable state

- **WHEN** a version directory is inspected after the server has run
- **THEN** it contains no world data and no operator-editable configuration
- **AND** removing it destroys neither

### Requirement: First run bootstraps a server installation

When no Bedrock installation is present, cobble SHALL be able to acquire and install the current version so that a fresh deployment reaches a runnable state without manual steps. A first run SHALL also establish the separated mutable-state location.

#### Scenario: No installation present at first run

- **WHEN** cobble starts and no Bedrock installation exists
- **THEN** the current version is acquired and installed
- **AND** it is made the active version
- **AND** the separated mutable-state location is established

#### Scenario: Download is incomplete or corrupt

- **WHEN** an acquired archive cannot be extracted successfully
- **THEN** no partially extracted version is left designated as active
- **AND** the failure is reported

#### Scenario: Installation already present

- **WHEN** cobble starts and a Bedrock installation already exists
- **THEN** no download is performed
- **AND** the existing installation remains active

#### Scenario: A fresh install requires no migration

- **WHEN** a deployment is bootstrapped from nothing
- **THEN** its mutable state is laid out in the separated location from the start
- **AND** no migration of an earlier layout is performed
