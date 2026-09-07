## Purpose

Acquiring the Bedrock Dedicated Server, laying out its files on disk, and installing cobble as a supervised service on a Proxmox LXC container — including the versioned directory structure and state location that later backup and update mechanisms depend on.

## ADDED Requirements

### Requirement: Platform compatibility is verified before installation

Because the Bedrock Dedicated Server is published only for 64-bit x86 and requires a minimum system library version, installation SHALL verify platform compatibility and fail with an explanatory message rather than producing an obscure runtime error.

#### Scenario: Unsupported architecture

- **WHEN** installation is attempted on a machine that is not 64-bit x86
- **THEN** installation fails
- **AND** the message states that the Bedrock server is unavailable for this architecture

#### Scenario: System libraries too old

- **WHEN** installation is attempted where the system C library is older than the Bedrock server requires
- **THEN** installation fails
- **AND** the message identifies the required minimum version

### Requirement: The current server version can be resolved

Cobble SHALL determine the current released version of the Bedrock Dedicated Server and its download location from the vendor's published source, without scraping web pages.

#### Scenario: Version is resolved

- **WHEN** the current version is requested
- **THEN** the released version identifier and a download location for the Linux server are returned

#### Scenario: Vendor source is unreachable

- **WHEN** the vendor source cannot be reached or returns an unusable response
- **THEN** the failure is reported and logged
- **AND** an already-installed server continues running unaffected

#### Scenario: Requests identify a client

- **WHEN** cobble requests the vendor source or a download
- **THEN** the request identifies a client agent
- **AND** requests that omit this are not made, as the vendor rejects them

### Requirement: Server installations are stored per version

Cobble SHALL store each Bedrock server installation in its own directory named for its version, and SHALL designate the active installation by an indirection that can be changed without moving files.

#### Scenario: A version is installed

- **WHEN** a Bedrock server version is installed
- **THEN** its files are placed in a directory identified by that version
- **AND** existing version directories are left unmodified

#### Scenario: Active version is designated

- **WHEN** a version is made active
- **THEN** the active-installation indirection points at that version's directory
- **AND** the change does not require copying or moving installation files

### Requirement: Cobble's own state is stored separately from the server

Cobble SHALL store its own durable state in a dedicated directory, separate from the Bedrock installation, so that state is not affected when a server version is replaced.

#### Scenario: Server version is replaced

- **WHEN** the active Bedrock version changes
- **THEN** cobble's state directory and its contents are unaffected

#### Scenario: State directory is treated as a unit

- **WHEN** a consumer needs to capture cobble's durable state
- **THEN** the state directory is the unit of capture
- **AND** files added to it later are included without that consumer being changed

### Requirement: First run bootstraps a server installation

When no Bedrock installation is present, cobble SHALL be able to acquire and install the current version so that a fresh deployment reaches a runnable state without manual steps.

#### Scenario: No installation present at first run

- **WHEN** cobble starts and no Bedrock installation exists
- **THEN** the current version is acquired and installed
- **AND** it is made the active version

#### Scenario: Download is incomplete or corrupt

- **WHEN** an acquired archive cannot be extracted successfully
- **THEN** no partially extracted version is left designated as active
- **AND** the failure is reported

#### Scenario: Installation already present

- **WHEN** cobble starts and a Bedrock installation already exists
- **THEN** no download is performed
- **AND** the existing installation remains active

### Requirement: Cobble runs as a supervised system service

Cobble SHALL be installable as a system service that starts automatically when the host boots and restarts if it exits unexpectedly.

#### Scenario: Host reboots

- **WHEN** the host is rebooted after installation
- **THEN** cobble starts automatically without operator action

#### Scenario: Cobble exits unexpectedly

- **WHEN** the cobble process exits unexpectedly
- **THEN** the service supervisor restarts it

#### Scenario: Service is stopped by an operator

- **WHEN** an operator stops the service
- **THEN** the managed Bedrock server is shut down cleanly as part of stopping

### Requirement: Deployment requires no build toolchain on the host

The installed artifact SHALL contain a pre-built web interface. Installation SHALL NOT require a JavaScript runtime, package manager, or compiler on the target host.

#### Scenario: Installing on a minimal container

- **WHEN** cobble is installed on a container with no JavaScript runtime or compiler
- **THEN** installation succeeds
- **AND** the web interface is served correctly

### Requirement: The backup destination is a filesystem path

Cobble SHALL treat the backup destination as a filesystem path and SHALL NOT implement network storage protocols. Mounting remote storage is a host responsibility.

#### Scenario: Destination is a mounted remote share

- **WHEN** the configured destination is a path backed by remote storage mounted by the host
- **THEN** cobble writes to it as it would any other path
- **AND** no protocol-specific configuration is required from cobble
