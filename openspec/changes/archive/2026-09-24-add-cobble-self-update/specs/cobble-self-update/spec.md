# Spec Delta

## Purpose

Keeping cobble itself current: determining whether a newer stable cobble release has been published, and upgrading the installed cobble in place on operator request. The upgrade is performed by a privileged helper that cobble can ask to act but cannot direct beyond naming an official release.

## ADDED Requirements

### Requirement: The running cobble version is reported

Cobble SHALL report the version of cobble that is currently running through the programmatic interface.

#### Scenario: Version is requested

- **WHEN** a client requests cobble's version information
- **THEN** the running cobble version is returned
- **AND** it is the version of the code actually executing, not a value read from a separately editable file

### Requirement: Availability of a newer cobble release is determined

Cobble SHALL determine the latest stable release of cobble from the project's published releases, compare it with the running version, and report whether an update is available together with the latest version, a link to that release's page, and when the check was last performed. Drafts and pre-releases SHALL NOT be treated as available updates.

#### Scenario: A newer release exists

- **WHEN** the latest stable release is a higher version than the running version
- **THEN** an update is reported as available
- **AND** the latest version and a link to its release page are reported

#### Scenario: Running the latest release

- **WHEN** the latest stable release is the same version as the running version
- **THEN** no update is reported as available

#### Scenario: Running a version newer than the latest release

- **WHEN** the running version is higher than the latest stable release (for example, a development build)
- **THEN** no update is reported as available

#### Scenario: Only a pre-release is newer

- **WHEN** the only release newer than the running version is a draft or pre-release
- **THEN** no update is reported as available

### Requirement: Release checks are periodic, shared, and bounded

Cobble SHALL check for a newer release shortly after it starts and then periodically. It SHALL serve the most recent result to all clients from a single cached check rather than contacting the release source per client request. An operator SHALL be able to request an immediate check.

#### Scenario: Cobble starts

- **WHEN** cobble starts
- **THEN** a release check is performed without delaying the start of the Bedrock server or the web interface

#### Scenario: Many clients view the interface

- **WHEN** several browsers display the interface at the same time
- **THEN** they are all served the same cached result
- **AND** the release source is not contacted once per browser

#### Scenario: Operator requests a check

- **WHEN** an operator requests an immediate release check
- **THEN** a check is performed and its result replaces the cached result

### Requirement: An unreachable release source is not an error condition for the operator

When the release source cannot be reached or returns an unusable response, cobble SHALL report that update availability is unknown, SHALL retain the last successful result if any, SHALL log the failure, and SHALL continue operating normally.

#### Scenario: No internet access

- **WHEN** a release check fails because the release source is unreachable
- **THEN** update availability is reported as unknown, or as the last successful result if one exists
- **AND** the failure reason is available to the interface
- **AND** no other cobble function is affected

#### Scenario: Requests identify a client

- **WHEN** cobble contacts the release source
- **THEN** the request identifies a client agent that includes the running cobble version

### Requirement: Whether one-click upgrade is possible is reported

Cobble SHALL report whether the privileged upgrade helper is installed on the host. When it is not, cobble SHALL report the command an operator can run as root to upgrade manually.

#### Scenario: Helper installed

- **WHEN** the upgrade helper is installed
- **THEN** one-click upgrade is reported as available

#### Scenario: Helper absent

- **WHEN** the upgrade helper is not installed (for example, a deployment installed before this capability existed)
- **THEN** one-click upgrade is reported as unavailable
- **AND** the manual root upgrade command is reported

### Requirement: An upgrade can be requested for an available release

Cobble SHALL allow an operator to request an upgrade to the release reported as available. The request SHALL name the exact release version that was reported, not "whatever is latest" at the time the helper runs. Cobble SHALL refuse the request when no update is available, when the helper is not installed, when an upgrade is already pending or running, or while another maintenance operation is in progress.

#### Scenario: Upgrade requested

- **WHEN** an operator requests an upgrade while an update is available and the helper is installed
- **THEN** cobble captures a verified backup
- **AND** then records an upgrade request naming the exact reported release version
- **AND** the request is acknowledged

#### Scenario: A newer release is published after the check

- **WHEN** a further release is published between the check and the helper acting
- **THEN** the release named in the request is installed, not the later one

#### Scenario: The pre-upgrade backup fails

- **WHEN** the backup captured before an upgrade fails
- **THEN** no upgrade request is recorded
- **AND** the failure is reported

#### Scenario: Refused while maintenance is in progress

- **WHEN** an upgrade is requested while a backup, update, restore, or import is in progress
- **THEN** the request is refused with a distinguishable reason

#### Scenario: Refused when nothing to upgrade to

- **WHEN** an upgrade is requested while no update is reported as available
- **THEN** the request is refused with a distinguishable reason

#### Scenario: Refused when already pending

- **WHEN** an upgrade is requested while an earlier upgrade request is pending or running
- **THEN** the request is refused
- **AND** at most one upgrade runs at a time

### Requirement: The upgrade is performed by a privileged helper cobble cannot direct

The upgrade SHALL be performed by a helper that runs with the privileges needed to replace cobble's installation and service definition. Cobble itself SHALL NOT gain those privileges. The helper SHALL accept from cobble only a release version identifier. It SHALL reject anything that is not a well-formed version identifier, SHALL obtain the installer and application only from the project's official releases for that version, and SHALL verify each downloaded file against the checksum published with the release before running or installing anything.

#### Scenario: Well-formed request

- **WHEN** the helper receives a request naming a well-formed release version
- **THEN** it downloads that release's installer and application package from the official release
- **AND** verifies both against the published checksums
- **AND** runs that release's installer to upgrade in place

#### Scenario: Malformed request

- **WHEN** the helper receives a request whose content is not a well-formed release version identifier
- **THEN** nothing is downloaded or installed
- **AND** the request is recorded as rejected

#### Scenario: Checksum mismatch

- **WHEN** a downloaded file does not match its published checksum
- **THEN** nothing is installed
- **AND** the upgrade is recorded as failed

#### Scenario: Cobble remains unprivileged

- **WHEN** cobble is running normally
- **THEN** it cannot itself modify its installation directory, its service definition, or system packages

### Requirement: An upgrade restarts cobble and preserves the server's running intent

Completing an upgrade SHALL restart cobble. Restarting cobble SHALL shut the Bedrock server down cleanly. After the restart, the Bedrock server SHALL be running if and only if it was intended to be running before the upgrade.

#### Scenario: Server was running

- **WHEN** an upgrade completes while the Bedrock server was intended to be running
- **THEN** the server is shut down cleanly before cobble is replaced
- **AND** it is running again once the upgraded cobble has started

#### Scenario: Server was stopped

- **WHEN** an upgrade completes while the Bedrock server was intentionally stopped
- **THEN** it remains stopped after the upgraded cobble has started

### Requirement: The upgrade outcome is recorded and reported

The outcome of the most recent upgrade SHALL be recorded durably and reported by cobble after it restarts. It SHALL include the version upgraded from, the version upgraded to, whether it succeeded, when it finished, and diagnostic output on failure. A failed upgrade SHALL leave the previously installed cobble running.

#### Scenario: Upgrade succeeds

- **WHEN** an upgrade completes successfully
- **THEN** the upgraded cobble reports the previous and new versions, success, and the completion time

#### Scenario: Upgrade fails before installation

- **WHEN** an upgrade fails during download or verification
- **THEN** the previously installed cobble continues running
- **AND** the failure and its diagnostic output are reported

#### Scenario: Upgrade is in progress

- **WHEN** an upgrade request is pending or running
- **THEN** cobble reports that an upgrade is in progress
