## MODIFIED Requirements

### Requirement: Backups are captured on a recurring schedule

Cobble SHALL capture a backup on a recurring schedule, independently configurable from the update-check schedule. The schedule SHALL support daily, weekly, or monthly frequency, SHALL be capable of being disabled, and, when it coincides with a due update-check run, SHALL still be coordinated with it so the server is stopped at most once.

#### Scenario: The scheduled time arrives

- **WHEN** the scheduled time is reached and the backup schedule is enabled
- **THEN** a backup is captured

#### Scenario: The next scheduled run is observable

- **WHEN** the backup schedule is enabled
- **THEN** the time of the next scheduled backup is reported

#### Scenario: A scheduled backup and a scheduled update coincide

- **WHEN** the backup schedule and the update-check schedule are independently configured but both fall due at or near the same time
- **THEN** they are performed as a single ordered sequence with the backup first
- **AND** the server is not stopped more than once for the pair

#### Scenario: The schedules do not coincide

- **WHEN** the backup schedule is due and the update-check schedule is not
- **THEN** the backup runs on its own, unaffected by the update-check schedule's cadence
