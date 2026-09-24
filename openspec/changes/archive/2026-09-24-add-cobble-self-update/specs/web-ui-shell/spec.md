# Spec Delta

## ADDED Requirements

### Requirement: The cobble version and its update state are shown in the header

The interface header SHALL show the running cobble version in square brackets beside the brand, for example `[0.4.0]`. It SHALL be green when no newer release is known. When a newer release is available, it SHALL be orange, SHALL read `[<version> update available]` with the running version, and SHALL link to that release's page on GitHub. When update availability is unknown, the version SHALL be shown without claiming the installation is current or out of date.

#### Scenario: Running the latest release

- **WHEN** the interface loads and no newer cobble release is available
- **THEN** the header shows `[<running version>]` in green beside the brand

#### Scenario: A newer release is available

- **WHEN** a newer cobble release is available
- **THEN** the header shows `[<running version> update available]` in orange
- **AND** activating it opens the release's page on GitHub

#### Scenario: Availability unknown

- **WHEN** the release check has not succeeded
- **THEN** the header shows `[<running version>]` without an update indication
- **AND** no error is shown in the header

#### Scenario: Availability changes while the interface is open

- **WHEN** a release check completes and changes the reported availability
- **THEN** the header reflects it without the operator refreshing the page

### Requirement: Cobble upgrades are available from the settings screen

The interface's Settings screen SHALL present cobble's installed version, the latest known release, when it was last checked, a link to the release notes, an action to check now, and the outcome of the most recent upgrade. When an update is available and one-click upgrade is possible, it SHALL offer an upgrade action. That action SHALL require confirmation that states the server will be stopped and players disconnected. When one-click upgrade is not possible, it SHALL instead show the root command to upgrade manually, with a way to copy it.

#### Scenario: Upgrade offered

- **WHEN** an update is available and one-click upgrade is possible
- **THEN** an action to upgrade to the named version is offered
- **AND** activating it asks for confirmation that states the server will be stopped and players disconnected

#### Scenario: Helper not installed

- **WHEN** an update is available but one-click upgrade is not possible
- **THEN** the manual root upgrade command is shown with a copy action
- **AND** no upgrade button is offered

#### Scenario: Maintenance in progress

- **WHEN** a backup, update, restore, or import is in progress
- **THEN** the upgrade action is unavailable

#### Scenario: Distinguished from Bedrock server updates

- **WHEN** the operator views the cobble upgrade controls
- **THEN** they are labelled as concerning cobble itself, distinct from the Bedrock server's version and updates

### Requirement: The interface follows an upgrade through the restart

After an upgrade is requested, the interface SHALL indicate that the upgrade is in progress, SHALL tolerate losing its connection while cobble restarts, and SHALL load the new version of the interface once cobble reports a different running version. It SHALL then show the recorded upgrade outcome.

#### Scenario: Upgrade succeeds

- **WHEN** cobble restarts at a new version after an upgrade the operator requested
- **THEN** the interface reloads itself onto the new version without operator action
- **AND** the header shows the new version

#### Scenario: Upgrade fails

- **WHEN** an upgrade fails and the previous cobble keeps running
- **THEN** the interface shows the failure and its diagnostic output
