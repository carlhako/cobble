## Purpose

A durable, append-only record of every update cobble has successfully applied, so an operator can see when the installed Bedrock version changed historically, independent of the single most-recent-result view.

## Requirements

### Requirement: A successful update is recorded in history

Cobble SHALL append a record to version history whenever an update completes successfully, noting the version updated from, the version updated to, when it happened, and whether it was scheduled or manually requested.

#### Scenario: A scheduled update succeeds

- **WHEN** a scheduled update completes successfully
- **THEN** a history record is appended noting the from-version, the to-version, the time, and that it was scheduled

#### Scenario: A manually requested update succeeds

- **WHEN** an operator-requested update completes successfully
- **THEN** a history record is appended noting that it was manually requested

### Requirement: Only successful updates are recorded in history

Version history SHALL record completed, successful updates only. A check that finds no newer version, a failed update, and a rolled-back update SHALL NOT appear there.

#### Scenario: No newer version is available

- **WHEN** an update check finds the installed version is already current
- **THEN** no record is appended to version history

#### Scenario: An update fails or is rolled back

- **WHEN** an update attempt fails, is rolled back, or reaches a terminal state
- **THEN** no record is appended to version history
- **AND** the outcome remains visible through the existing failed-update surfaces

### Requirement: Version history is listed to operators

Cobble SHALL report the full version history on request, ordered newest first.

#### Scenario: History is requested

- **WHEN** version history is requested
- **THEN** every recorded update is returned, most recent first, with its from-version, to-version, time, and trigger

#### Scenario: No update has ever succeeded

- **WHEN** version history is requested and none have been recorded
- **THEN** an empty list is returned
- **AND** no error is raised
