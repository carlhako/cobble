# Spec Delta

## MODIFIED Requirements

### Requirement: The shell accommodates screens added by later work

The interface SHALL provide navigation and layout structure into which additional sections can be added without restructuring the shell. A section SHALL be listed in navigation unless it is declared as reachable only from elsewhere in the interface. Such a section SHALL still be reachable at its own address.

#### Scenario: A new section is added

- **WHEN** a new section is added to the interface
- **THEN** it appears in navigation
- **AND** existing sections are unaffected

#### Scenario: A section is reachable only from elsewhere

- **WHEN** a section is declared as not listed in navigation
- **THEN** it does not appear in the navigation bar
- **AND** opening its address directly shows it inside the shell

### Requirement: The cobble version and its update state are shown in the header

The interface header SHALL show the running cobble version in square brackets beside the brand, for example `[0.4.0]`. It SHALL be green when no newer release is known. When a newer release is available, it SHALL be orange and SHALL read `[<version> update available]` with the running version. When update availability is unknown, the version SHALL be shown without claiming the installation is current or out of date. In every state, activating the version SHALL open the cobble page within the interface, not an external site.

#### Scenario: Running the latest release

- **WHEN** the interface loads and no newer cobble release is available
- **THEN** the header shows `[<running version>]` in green beside the brand
- **AND** activating it opens the cobble page

#### Scenario: A newer release is available

- **WHEN** a newer cobble release is available
- **THEN** the header shows `[<running version> update available]` in orange
- **AND** activating it opens the cobble page, not the release's page on GitHub

#### Scenario: Availability unknown

- **WHEN** the release check has not succeeded
- **THEN** the header shows `[<running version>]` without an update indication
- **AND** no error is shown in the header
- **AND** activating it opens the cobble page

#### Scenario: Availability changes while the interface is open

- **WHEN** a release check completes and changes the reported availability
- **THEN** the header reflects it without the operator refreshing the page

## ADDED Requirements

### Requirement: Cobble upgrades are available from the cobble page

The interface SHALL provide a cobble page, reached from the header version and not listed in the navigation bar. It SHALL present cobble's installed version, the latest known release, whether an update is available, when the release check last ran, an action to check now, a link to the latest release's page on GitHub, and the outcome of the most recent upgrade. When an update is available and one-click upgrade is possible, it SHALL offer an upgrade action. That action SHALL require confirmation that states the server will be stopped and players disconnected. When one-click upgrade is not possible, the page SHALL instead show the root command to upgrade manually, with a way to copy it. The cobble upgrade controls SHALL NOT appear on any other screen.

#### Scenario: Upgrade offered

- **WHEN** an update is available and one-click upgrade is possible
- **THEN** the cobble page offers an action to upgrade to the named version
- **AND** activating it asks for confirmation that states the server will be stopped and players disconnected

#### Scenario: Helper not installed

- **WHEN** an update is available but one-click upgrade is not possible
- **THEN** the cobble page shows the manual root upgrade command with a copy action
- **AND** no upgrade button is offered

#### Scenario: Maintenance in progress

- **WHEN** a backup, update, restore, or import is in progress
- **THEN** the upgrade action is unavailable

#### Scenario: Distinguished from Bedrock server updates

- **WHEN** the operator views the cobble page
- **THEN** it is labelled as concerning cobble itself, distinct from the Bedrock server's version and updates

#### Scenario: Not on the settings tab

- **WHEN** the operator views the Updates & Backups section's Settings tab
- **THEN** no cobble version or upgrade controls are shown there

### Requirement: The cobble page shows the latest release's notes

The cobble page SHALL show the notes of the latest known cobble release, with its version and publish date, formatted from Markdown. It SHALL do so whether or not that release is newer than the running version. Markup in the notes SHALL NOT be able to run script or inject raw HTML into the interface, and links in the notes SHALL open outside the interface. When the latest release has no notes, or no release is known, the page SHALL say so instead of showing an empty area.

#### Scenario: Update available with notes

- **WHEN** a newer release with notes is available
- **THEN** the cobble page shows that release's version, publish date, and formatted notes above or beside the upgrade action

#### Scenario: Running the latest release

- **WHEN** the running version is the latest release
- **THEN** the cobble page shows that release's notes

#### Scenario: Notes contain raw HTML

- **WHEN** the release notes contain an HTML tag such as `<script>` or `<img onerror=...>`
- **THEN** it is not rendered as HTML and no script runs

#### Scenario: Release has no notes

- **WHEN** the latest release was published with empty notes
- **THEN** the page states that no release notes were published and still links to the release on GitHub

#### Scenario: No release known

- **WHEN** no release check has ever succeeded
- **THEN** the page states that the latest release is unknown and shows no notes area

## REMOVED Requirements

### Requirement: Cobble upgrades are available from the settings screen

**Reason**: The controls were on a non-default tab inside Updates & Backups and were hard to find. They move to the cobble page, which the header version opens.
**Migration**: Replaced by "Cobble upgrades are available from the cobble page". Operators click the version badge in the header instead of opening Updates & Backups, then Settings.
