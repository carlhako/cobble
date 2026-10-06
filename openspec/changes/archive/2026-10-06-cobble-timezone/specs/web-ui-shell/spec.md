# Spec Delta

## MODIFIED Requirements

### Requirement: Cobble upgrades are available from the cobble page

The interface SHALL provide a cobble page, reached from the header version and from the header settings cog, and not listed in the navigation bar. It SHALL present cobble's installed version, the latest known release, whether an update is available, when the release check last ran, an action to check now, a link to the latest release's page on GitHub, and the outcome of the most recent upgrade. When an update is available and one-click upgrade is possible, it SHALL offer an upgrade action. That action SHALL require confirmation that states the server will be stopped and players disconnected. When one-click upgrade is not possible, the page SHALL instead show the root command to upgrade manually, with a way to copy it. The cobble upgrade controls SHALL NOT appear on any other screen.

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

## ADDED Requirements

### Requirement: The header offers a settings cog

The interface header SHALL show a cog control, aligned to the right of the header, that opens the cobble page. It SHALL have an accessible name identifying it as cobble settings. It SHALL stay on the header's top row at phone width rather than wrapping with the navigation bar. It SHALL indicate when the cobble page is the current page.

#### Scenario: Operator activates the cog

- **WHEN** an operator activates the header cog
- **THEN** the cobble page opens within the interface

#### Scenario: Narrow screen

- **WHEN** the interface is viewed at phone width
- **THEN** the cog is visible at the right of the header's top row without horizontal scrolling

### Requirement: Cobble settings are editable from the cobble page

The cobble page SHALL show a Settings area above its version and upgrade content. In it, the operator SHALL be able to choose the cobble timezone from the timezone names cobble accepts, filterable by name, or choose the host default. The host default option SHALL name the host's timezone. When the browser's timezone differs from the effective cobble timezone, the area SHALL offer a single action to set the cobble timezone to the browser's, naming that timezone. Saving SHALL go through the programmatic interface, and a rejected value SHALL be shown with its reason. The area SHALL show the effective timezone and its current UTC offset.

#### Scenario: Operator picks a timezone

- **WHEN** an operator selects `Australia/Brisbane` in the cobble page's Settings area and saves
- **THEN** the cobble timezone is set to `Australia/Brisbane`
- **AND** the area shows `Australia/Brisbane` with its offset as the effective timezone

#### Scenario: Operator uses the browser's timezone

- **WHEN** the browser's timezone is `Australia/Brisbane`, the cobble timezone is the host default of `UTC`, and the operator activates the action to use the browser's timezone
- **THEN** the cobble timezone is set to `Australia/Brisbane`

#### Scenario: Settings appear before upgrade content

- **WHEN** an operator opens the cobble page
- **THEN** the Settings area is shown above the cobble version, release notes, and upgrade controls

#### Scenario: Operator returns to the host default

- **WHEN** an operator chooses the host default option and saves
- **THEN** the cobble timezone is cleared and the area shows the host's timezone as effective

### Requirement: Schedule times are presented in the cobble timezone

Wherever the interface edits a schedule's time or shows a next scheduled run, it SHALL name the effective cobble timezone. It SHALL present next-run times as clock times in that timezone, not converted to the browser's timezone.

#### Scenario: Schedule editor names its timezone

- **WHEN** the cobble timezone is `Australia/Brisbane` and an operator views the backup schedule's time on the Updates & Backups Settings tab
- **THEN** the time input is labelled as Brisbane time, with the timezone named

#### Scenario: Next run viewed from a browser in another timezone

- **WHEN** the cobble timezone is `UTC`, the next backup is at 04:00 UTC, and the browser is in `Australia/Brisbane`
- **THEN** the next run is shown as 04:00 with `UTC` named
- **AND** it is not shown as 04:00 without a timezone

### Requirement: A timezone mismatch between browser and cobble is surfaced

When the browser's timezone and the effective cobble timezone would put a scheduled clock time at different instants at any point in the coming year, the Updates & Backups section and the cobble page's Settings area SHALL say that schedules run in the cobble timezone, naming both timezones. The notice SHALL offer to set the cobble timezone to the browser's. The operator SHALL be able to dismiss the notice in that browser. A dismissed notice SHALL return if either timezone changes. Timezones that keep the same clock time all year SHALL NOT be treated as a mismatch.

#### Scenario: Browser ahead of a UTC host

- **WHEN** the browser is in `Australia/Brisbane` and the effective cobble timezone is `UTC`
- **THEN** the Updates & Backups section shows that schedules run in UTC while the browser is in Australia/Brisbane
- **AND** it offers to switch cobble to `Australia/Brisbane`

#### Scenario: Equivalent timezones

- **WHEN** the browser reports `Australia/Melbourne` and the cobble timezone is `Australia/Sydney`
- **THEN** no mismatch notice is shown

#### Scenario: Zones that differ only during daylight saving

- **WHEN** the browser is in `Australia/Sydney` and the cobble timezone is `Australia/Brisbane`
- **THEN** the mismatch notice is shown, even during months when their offsets are equal

#### Scenario: Notice dismissed

- **WHEN** an operator dismisses the mismatch notice
- **THEN** it is not shown again in that browser for the same pair of timezones
- **AND** it is shown again if the cobble timezone or the browser's timezone changes
