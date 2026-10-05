## Purpose

Bringing a world that originated elsewhere onto this server from an operator-supplied archive — how the archive is accepted and staged, how a world is located and identified inside it, what the operator is told before committing, and how the world already on the server is replaced without becoming unrecoverable.

## Requirements

### Requirement: A world archive is uploaded and applied as two separate steps

Cobble SHALL accept a world archive as an upload that is held without being applied, and SHALL apply a held archive only on a separate, explicit operator request. The upload SHALL NOT modify the server's world, configuration, or run state.

#### Scenario: An archive is uploaded

- **WHEN** an operator uploads a world archive
- **THEN** the archive is held for a subsequent apply
- **AND** the server's world is unchanged
- **AND** the server's run state is unchanged

#### Scenario: An upload is never applied

- **WHEN** an archive is uploaded and no apply is requested
- **THEN** the server's world remains as it was

#### Scenario: Apply is requested with nothing held

- **WHEN** an apply is requested and no archive is held
- **THEN** the request is refused
- **AND** the server's world is unchanged

### Requirement: An archive is streamed to storage rather than held in memory

Because a world archive may be several gigabytes, cobble SHALL write an upload to storage as it is received and SHALL NOT require memory proportional to the archive's size.

#### Scenario: A large archive is uploaded

- **WHEN** an archive substantially larger than available memory is uploaded
- **THEN** the upload completes
- **AND** cobble's memory use does not grow in proportion to the archive's size

#### Scenario: An upload is interrupted

- **WHEN** an upload does not complete
- **THEN** the incomplete transfer is not held as an archive available to apply
- **AND** any previously held archive is not left in a partially overwritten state

### Requirement: Exactly one archive is held at a time and the slot is kept clean

Cobble SHALL hold at most one uploaded archive. A new upload SHALL replace any archive already held. A held archive SHALL be discarded once it has been applied, and SHALL NOT persist indefinitely when it is never applied.

#### Scenario: A second archive is uploaded

- **WHEN** an archive is uploaded while another is already held
- **THEN** the newly uploaded archive is the one held
- **AND** the previously held archive no longer occupies storage

#### Scenario: An archive is applied

- **WHEN** an apply completes, whether it succeeds or fails
- **THEN** the held archive no longer occupies storage

#### Scenario: An abandoned archive is left behind

- **WHEN** cobble starts and an archive is held from an earlier run
- **THEN** the archive does not remain held indefinitely
- **AND** the storage it occupied is reclaimed

#### Scenario: An operator discards a held archive

- **WHEN** an operator discards the held archive
- **THEN** it is no longer held
- **AND** the storage it occupied is reclaimed

### Requirement: A world is located inside an archive by structure

Because Bedrock worlds are distributed in several archive layouts, cobble SHALL locate a world by recognising its structure rather than by assuming a path within the archive. A world SHALL be recognised by a level data file accompanied by a sibling world database directory.

#### Scenario: The archive is a full server backup

- **WHEN** an archive contains a world beneath a top-level worlds directory, alongside server files unrelated to the world
- **THEN** the world is located
- **AND** the unrelated server files are ignored

#### Scenario: The archive is a zipped world folder

- **WHEN** an archive contains a world inside a single named directory at its root
- **THEN** the world is located

#### Scenario: The archive holds a world at its root

- **WHEN** an archive contains the level data file and world database directory at its root, with no enclosing directory
- **THEN** the world is located

#### Scenario: The archive contains no world

- **WHEN** an archive contains no recognisable world
- **THEN** it is refused with a reason stating that no Bedrock world was found
- **AND** nothing is applied

#### Scenario: The archive contains more than one world

- **WHEN** an archive contains more than one recognisable world
- **THEN** it is refused as ambiguous
- **AND** the reason names how many worlds were found
- **AND** nothing is applied

#### Scenario: The archive is not a readable archive

- **WHEN** an uploaded file is not a readable archive, or is corrupt
- **THEN** it is refused with a reason
- **AND** nothing is applied

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

### Requirement: A world newer than the installed server is refused

Because a server cannot load a world written by a later version and may damage it in the attempt, cobble SHALL refuse to import a world whose last-opened Bedrock version is newer than the installed version. This refusal SHALL NOT be overridable by confirmation.

#### Scenario: The world is newer than the installed server

- **WHEN** an apply is requested for a world whose last-opened version is newer than the installed version
- **THEN** the request is refused
- **AND** the reason names both versions
- **AND** the server's world is unchanged

#### Scenario: The operator confirms a newer world anyway

- **WHEN** an operator confirms an apply for a world newer than the installed version
- **THEN** the request is still refused

### Requirement: A world older than the installed server is confirmed before it is applied

Because the installed server upgrades an older world in place and the upgrade cannot be undone, cobble SHALL warn the operator and SHALL apply such a world only after explicit confirmation.

#### Scenario: The world predates the installed server

- **WHEN** an apply is requested for a world whose last-opened version is older than the installed version and the operator has not confirmed
- **THEN** the operator is warned that the world will be upgraded irreversibly by the installed server
- **AND** the world is not applied

#### Scenario: The operator confirms an older world

- **WHEN** an operator confirms an apply for a world older than the installed version
- **THEN** the import proceeds

#### Scenario: The versions match or the world's version is unknown

- **WHEN** an apply is requested for a world whose last-opened version equals the installed version, or cannot be determined
- **THEN** no version warning is raised

### Requirement: Free space is verified before an import begins

Because an import needs room for the archive, the world extracted from it, and a capture of the world being replaced at the same time, cobble SHALL verify that sufficient space is available before beginning, and SHALL refuse rather than fail partway.

#### Scenario: Insufficient space to hold an upload

- **WHEN** an upload is requested and there is not enough space to hold the archive
- **THEN** the upload is refused before it begins
- **AND** the reason states that there is insufficient space

#### Scenario: Insufficient space to apply

- **WHEN** an apply is requested and there is not enough space for the extracted world and a capture of the world being replaced
- **THEN** the apply is refused
- **AND** the server is not stopped
- **AND** the server's world is unchanged

#### Scenario: Sufficient space is available

- **WHEN** space is sufficient for the archive, the extracted world, and the capture
- **THEN** the import proceeds

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

### Requirement: An import is performed with the server stopped

Because the world is written continuously while the server runs, cobble SHALL stop the server before replacing the world and SHALL return it to its previous run state afterwards. An import SHALL be refused if the server cannot be stopped cleanly.

#### Scenario: Import while the server is running

- **WHEN** an import is applied and the server is running
- **THEN** the server is stopped using the clean shutdown behaviour before the world is replaced
- **AND** the server is started again after the import completes

#### Scenario: Import while the server is stopped

- **WHEN** an import is applied and the server is not running
- **THEN** the import proceeds without starting the server
- **AND** the server is not started afterwards

#### Scenario: The server cannot be stopped cleanly

- **WHEN** an import is requested and the server cannot be stopped cleanly
- **THEN** the existing world is not replaced
- **AND** the failure is reported

### Requirement: The world being replaced is captured before it is destroyed

Because an import destroys the world already on the server, cobble SHALL capture the state being replaced as a restorable backup before removing it, and SHALL abandon the import if that capture cannot be made.

#### Scenario: An import is applied

- **WHEN** an import is applied
- **THEN** the state being replaced is captured and verified before anything is removed
- **AND** the capture is reported so the operator can restore it

#### Scenario: The capture cannot be made

- **WHEN** the state being replaced cannot be captured or the capture does not verify
- **THEN** the world is not replaced
- **AND** the failure is reported

#### Scenario: The import fails partway through

- **WHEN** an import fails after the world has begun to be replaced
- **THEN** the failure is reported
- **AND** the report names the capture of the replaced state
- **AND** the capture remains restorable

### Requirement: An imported world's own rules do not become the server's rules

Because a world carries its own gamerule values and an imported world's values were set by another server, cobble SHALL treat an import the same as a restore for the purpose of gamerules, so that the server's configured rules are reasserted rather than replaced by the imported world's.

#### Scenario: A world with differing gamerules is imported

- **WHEN** a world whose gamerule values differ from the server's configured values is imported
- **THEN** the server's configured values are reasserted once the server is next ready
- **AND** the imported world's values are not adopted as the server's

### Requirement: An import does not run concurrently with another maintenance operation

Cobble SHALL perform at most one of import, backup, restore, or update at a time, and SHALL refuse a request that would overlap another.

#### Scenario: An import is requested during another operation

- **WHEN** an import is requested while a backup, restore, or update is in progress
- **THEN** the import does not begin
- **AND** the request fails with an error identifying the operation in progress

#### Scenario: Another operation is requested during an import

- **WHEN** a backup, restore, or update is requested while an import is in progress
- **THEN** it does not begin
- **AND** the request fails with an error identifying the import

### Requirement: Import progress is observable

Because an import stops the server and may take some time, cobble SHALL report the stage it has reached while the import runs.

#### Scenario: An import is in progress

- **WHEN** an import is running
- **THEN** the stage it has reached is reported
- **AND** the report distinguishes stopping the server, capturing the state being replaced, putting the world in place, and starting the server

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
