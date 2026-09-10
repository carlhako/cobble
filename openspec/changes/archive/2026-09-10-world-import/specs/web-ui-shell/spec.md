## ADDED Requirements

### Requirement: A world can be imported from the interface

The web interface SHALL provide a dedicated Import World section from which an operator can upload a world archive, see what cobble found inside it, and apply it.

#### Scenario: Operator opens the section

- **WHEN** an operator opens the Import World section
- **THEN** the section offers a world archive to be chosen and uploaded
- **AND** it states that importing replaces the world the server currently loads

#### Scenario: An archive is already held

- **WHEN** an operator opens the section and an archive is already held
- **THEN** the held archive's world is described
- **AND** the operator can apply it or discard it without uploading again

### Requirement: Upload progress is presented as it happens

Because a world archive may be large enough to take a noticeable time to transfer, the interface SHALL show the progress of an upload rather than only its completion.

#### Scenario: An upload is in progress

- **WHEN** an archive is being uploaded
- **THEN** the proportion transferred is shown and advances as the transfer proceeds

#### Scenario: An upload fails

- **WHEN** an upload does not complete
- **THEN** the failure is shown with its reason
- **AND** the operator can attempt the upload again

### Requirement: The interface describes the world before the operator commits

The interface SHALL present what cobble found in the held archive — the world's name, size, seed, and last-opened Bedrock version — before offering to apply it, so that the operator confirms against the world's identity rather than a file name.

#### Scenario: A held archive is described

- **WHEN** an archive has been uploaded and inspected
- **THEN** the world's name, size, seed, and last-opened Bedrock version are shown

#### Scenario: The archive was refused

- **WHEN** an uploaded archive contains no world, contains more than one world, or is not a readable archive
- **THEN** the reason is shown
- **AND** no apply action is offered

#### Scenario: The archive carries other server files

- **WHEN** the held archive also contains server configuration, allowlist, or permissions files
- **THEN** the interface reports that they are present and that they will not be imported

### Requirement: Importing is confirmed against what will be destroyed

Because an import destroys the world the server currently loads, the interface SHALL require an explicit confirmation that names both the world being installed and the world being replaced.

#### Scenario: Operator chooses to import

- **WHEN** an operator chooses to apply a held archive
- **THEN** a confirmation is presented naming the world to be installed and the world it will replace
- **AND** the confirmation states that the server will be stopped and restarted
- **AND** the confirmation states that a backup of the replaced world is taken first
- **AND** nothing is applied until the operator confirms

#### Scenario: The world predates the installed server

- **WHEN** the held world's last-opened Bedrock version is older than the installed version
- **THEN** the interface warns that the installed server will upgrade the world irreversibly
- **AND** requires a further explicit confirmation before applying

#### Scenario: The world is newer than the installed server

- **WHEN** the held world's last-opened Bedrock version is newer than the installed version
- **THEN** the interface states that the world cannot be imported and names both versions
- **AND** no apply action is offered

#### Scenario: Operator abandons the import

- **WHEN** an operator declines the confirmation
- **THEN** nothing is applied
- **AND** the archive remains held

### Requirement: Import progress and outcome are reflected without operator action

The interface SHALL reflect the stage of a running import and its outcome without the operator reloading or navigating.

#### Scenario: An import is running

- **WHEN** an import is in progress
- **THEN** the stage it has reached is shown and updates as it advances

#### Scenario: An import completes

- **WHEN** an import completes
- **THEN** the outcome is shown
- **AND** the backup holding the replaced world is named so the operator can restore it

#### Scenario: An import fails

- **WHEN** an import fails
- **THEN** the failure is shown with its reason
- **AND** where the world was already being replaced, the backup holding the replaced world is named

### Requirement: Importing is unavailable during maintenance

The interface SHALL NOT offer to apply an import while another maintenance operation is in progress, and SHALL say why.

#### Scenario: A backup, restore, or update is in progress

- **WHEN** an operator views the Import World section while another maintenance operation is in progress
- **THEN** the apply action is unavailable
- **AND** the operation in progress is named
