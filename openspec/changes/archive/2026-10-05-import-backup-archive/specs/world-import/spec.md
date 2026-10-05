# Spec Delta

## ADDED Requirements

### Requirement: Zip and gzip-compressed tar archives are both accepted

Cobble SHALL accept an uploaded archive in either zip form (including a `.mcworld` export) or gzip-compressed tar form, and SHALL recognise which form it is from the archive's content rather than from any file name. The form of an archive SHALL NOT determine how it is applied; only its contents SHALL.

#### Scenario: A zipped world is uploaded

- **WHEN** an operator uploads a zip archive holding a world
- **THEN** it is held and described as a world archive

#### Scenario: A gzip-compressed tar of a world folder is uploaded

- **WHEN** an operator uploads a gzip-compressed tar archive holding a world folder that is not a cobble backup
- **THEN** it is held and described as a world archive
- **AND** applying it imports the world exactly as a zipped world would be imported

#### Scenario: An archive's name does not match its content

- **WHEN** an uploaded archive's file name suggests one form but its content is the other
- **THEN** the archive is read according to its content

#### Scenario: A file in neither form is uploaded

- **WHEN** an uploaded file is neither a zip archive nor a gzip-compressed tar archive
- **THEN** it is refused as not a readable archive
- **AND** nothing is applied

#### Scenario: A gzip-compressed tar archive is corrupt

- **WHEN** an uploaded gzip-compressed tar archive is truncated or fails its integrity check
- **THEN** it is refused with a reason
- **AND** nothing is applied

### Requirement: A cobble backup archive is applied as a full restore

Cobble SHALL recognise an uploaded tar archive that carries cobble's backup manifest together with a server data directory and a cobble state directory as a cobble backup, regardless of which cobble instance produced it. Applying a held cobble backup SHALL replace the world, the server's configuration, allowlist, and permissions, and cobble's own durable state, with the restore behaviour defined for restoring a backup. A zip archive SHALL NOT be recognised as a cobble backup.

#### Scenario: A backup downloaded from another cobble instance is uploaded

- **WHEN** an operator uploads a backup archive retrieved from a different cobble instance
- **THEN** it is held and described as a cobble backup

#### Scenario: A held cobble backup is applied

- **WHEN** an operator applies a held cobble backup
- **THEN** the server's world, configuration, allowlist, and permissions match those in the backup
- **AND** cobble's durable state other than instance-local state matches that in the backup
- **AND** the state being replaced is captured and verified first
- **AND** the restore proceeds with the server stopped, as a restore of a held backup does

#### Scenario: A zip archive laid out like a cobble backup is uploaded

- **WHEN** an operator uploads a zip archive containing a manifest, a server data directory, and a cobble state directory
- **THEN** it is treated as a world archive, not a cobble backup

#### Scenario: A cobble backup holds more than one world

- **WHEN** an uploaded cobble backup contains more than one recognisable world
- **THEN** it is refused as ambiguous
- **AND** the reason names how many worlds were found
- **AND** nothing is applied

#### Scenario: A cobble backup holds no world

- **WHEN** an uploaded cobble backup contains no recognisable world
- **THEN** it is refused with a reason stating that no Bedrock world was found
- **AND** nothing is applied

#### Scenario: A cobble backup's recorded version is newer than the installed server

- **WHEN** an apply is requested for a cobble backup whose recorded Bedrock version is newer than the installed version
- **THEN** the request is refused, and confirmation cannot override the refusal
- **AND** the reason names both versions
- **AND** nothing is replaced

#### Scenario: A cobble backup's recorded version is older than the installed server

- **WHEN** an apply is requested for a cobble backup whose recorded Bedrock version is older than the installed version and the operator has not confirmed
- **THEN** the operator is warned that the world will be upgraded irreversibly by the installed server
- **AND** nothing is replaced until the operator confirms

### Requirement: A backup's recorded version stands in for an unreadable world version

When a world's last-opened Bedrock version cannot be read from the world itself and the archive carries a cobble backup manifest recording a Bedrock version, cobble SHALL use the recorded version for the version checks and SHALL report it as the world's version.

#### Scenario: The world's version is unreadable but the manifest records one

- **WHEN** a held archive's world has no readable last-opened version and its cobble manifest records a Bedrock version
- **THEN** the recorded version is reported
- **AND** the newer-world refusal and older-world confirmation apply using that version

#### Scenario: Neither version is available

- **WHEN** neither the world nor a cobble manifest provides a Bedrock version
- **THEN** the version is reported as unknown
- **AND** the archive remains applicable

## MODIFIED Requirements

### Requirement: An archive cannot write outside the destination when extracted

Cobble SHALL refuse an archive whose members would be written outside the intended destination, so that an operator-supplied file cannot place content elsewhere on the host. Cobble SHALL refuse an archive containing a hard link or a device, pipe, or other special file in any part it would extract, and SHALL NOT create a symbolic link from an uploaded archive.

#### Scenario: An archive member escapes the destination

- **WHEN** an archive contains a member whose path traverses above the extraction destination, or is an absolute path
- **THEN** the archive is refused
- **AND** no file is written outside the destination

#### Scenario: An archive member is a link

- **WHEN** an archive contains a link whose target lies outside the extraction destination
- **THEN** the archive is refused
- **AND** the link is not created

#### Scenario: An archive member is a hard link or special file

- **WHEN** an archive contains a hard link, device, pipe, or other special file in a part that would be extracted
- **THEN** the archive is refused
- **AND** nothing is applied

#### Scenario: A cobble backup carries the server payload links

- **WHEN** an uploaded cobble backup contains symbolic links that stay within the destination
- **THEN** the links are not extracted
- **AND** the server's own payload links are present after the restore

### Requirement: A held archive is described before it is applied

Cobble SHALL report what it found in a held archive so that an operator confirms against the archive's identity rather than against a file name. The report SHALL state whether the archive is a world archive or a cobble backup, and SHALL identify the world's name, its size, the seed it was generated from, and the Bedrock version it was last opened with. For a cobble backup the report SHALL additionally state when the backup was captured and that applying it replaces the server's configuration, access lists, and cobble's settings and history as well as the world.

#### Scenario: A held archive is inspected

- **WHEN** an operator inspects a held archive
- **THEN** whether it is a world archive or a cobble backup is reported
- **AND** the world's name, size, seed, and last-opened Bedrock version are reported

#### Scenario: A held cobble backup is inspected

- **WHEN** an operator inspects a held cobble backup
- **THEN** the time the backup was captured and its recorded Bedrock version are reported
- **AND** the operator is told that applying it replaces configuration, allowlist, permissions, and cobble's settings and history as well as the world

#### Scenario: The archive carries server files besides the world

- **WHEN** a held world archive also contains server configuration, allowlist, or permissions files
- **THEN** their presence is reported
- **AND** they are not applied by an import

#### Scenario: The world's last-opened version cannot be determined

- **WHEN** the Bedrock version a world was last opened with cannot be read and no cobble manifest records one
- **THEN** the version is reported as unknown
- **AND** the archive remains applicable

### Requirement: An import replaces the world the server loads

When a world archive is applied, cobble SHALL replace the world named by the level setting with the world from the archive, and SHALL NOT change the level setting itself, so that everything keyed to the world's name continues to refer to it.

#### Scenario: An import is applied

- **WHEN** a world archive is applied
- **THEN** the world named by the level setting holds the imported world's contents
- **AND** the level setting is unchanged

#### Scenario: The imported world was named differently

- **WHEN** the world inside a world archive was named differently from the world it replaces
- **THEN** the world is imported under the name the level setting already uses
- **AND** the world's own recorded display name matches the name it was imported under

#### Scenario: Worlds other than the one being replaced

- **WHEN** a world archive is applied and the server holds worlds other than the one named by the level setting
- **THEN** those other worlds are unchanged

#### Scenario: Server files in the archive are not applied

- **WHEN** a world archive is applied and it also contains server configuration, allowlist, or permissions files
- **THEN** the server's own configuration, allowlist, and permissions are unchanged
