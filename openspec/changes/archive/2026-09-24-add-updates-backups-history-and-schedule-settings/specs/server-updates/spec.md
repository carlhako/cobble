## MODIFIED Requirements

### Requirement: Updates are checked and applied on a recurring schedule

Cobble SHALL check for a newer version on a recurring schedule, independently configurable from the backup schedule, and SHALL apply an available update without operator involvement. The schedule SHALL support daily, weekly, or monthly frequency, SHALL be capable of being disabled, and, when it coincides with a due backup run, SHALL still be coordinated with it so the server is stopped at most once.

#### Scenario: The scheduled time arrives

- **WHEN** the scheduled time is reached and the schedule is enabled
- **THEN** a version check is performed
- **AND** an available update is applied

#### Scenario: The next scheduled run is observable

- **WHEN** the schedule is enabled
- **THEN** the time of the next scheduled run is reported

#### Scenario: The schedule is disabled

- **WHEN** the schedule is disabled
- **THEN** no automatic check or update occurs
- **AND** an update can still be requested on demand

#### Scenario: A scheduled update and a scheduled backup coincide

- **WHEN** the update-check schedule and the backup schedule are independently configured but both fall due at or near the same time
- **THEN** the backup is performed first, then the version check and any available update
- **AND** the server is not stopped more than once for the pair

#### Scenario: The schedules do not coincide

- **WHEN** the update-check schedule is due and the backup schedule is not
- **THEN** the check (and any applied update) runs on its own, unaffected by the backup schedule's cadence
