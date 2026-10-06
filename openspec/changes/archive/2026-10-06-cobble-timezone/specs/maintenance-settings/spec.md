# Spec Delta

## ADDED Requirements

### Requirement: Schedules run in the cobble timezone

Cobble SHALL interpret the time of day, the day of the week, and the day of the month of both the backup schedule and the update-check schedule in the effective cobble timezone (see `cobble-settings`). This SHALL hold whatever timezone the host or the cobble process is set to. A change to the cobble timezone SHALL recompute both schedules' next runs without a restart.

#### Scenario: Timezone differs from the host's

- **WHEN** the host's local timezone is `UTC`, the cobble timezone is `Australia/Brisbane`, and the backup schedule is daily at 04:00
- **THEN** the scheduled backup runs at 04:00 Brisbane time, which is 18:00 UTC the previous day
- **AND** it does not run at 04:00 UTC

#### Scenario: Timezone changed while cobble is running

- **WHEN** an operator changes the cobble timezone while a schedule is enabled
- **THEN** that schedule's next run is recomputed in the new timezone
- **AND** cobble does not need to be restarted for the change to take effect

#### Scenario: Weekly day follows the cobble timezone

- **WHEN** a weekly schedule is set for Monday at 04:00 and the cobble timezone is ahead of UTC
- **THEN** it runs on Monday at 04:00 in the cobble timezone, even though that instant is still Sunday in UTC

### Requirement: Daylight-saving transitions neither skip nor repeat a scheduled run

A daylight-saving change can remove an hour from a day or repeat one. Each schedule SHALL run exactly once on every day it is due, including days with a transition. When the scheduled time does not exist on a day because the clocks go forward over it, the run SHALL happen once, later by the length of the gap. When the scheduled time occurs twice on a day because the clocks go back over it, the run SHALL happen once, at its first occurrence.

#### Scenario: Scheduled time falls in a spring-forward gap

- **WHEN** a daily schedule is set for 02:30 and on that day clocks in the cobble timezone go forward from 02:00 to 03:00
- **THEN** the run happens once that day, at 03:30
- **AND** it is not skipped
- **AND** on the following day it runs at 02:30

#### Scenario: Scheduled time is repeated at fall-back

- **WHEN** a daily schedule is set for 02:30 and on that day clocks in the cobble timezone go back from 03:00 to 02:00
- **THEN** the run happens once that day, at the first 02:30
- **AND** it does not run again when 02:30 recurs an hour later

#### Scenario: Schedule outside the transition

- **WHEN** a daily schedule is set for 04:00 and clocks change at 02:00 that day
- **THEN** the run happens once at 04:00 local time on the new offset

### Requirement: Next-run times identify their instant

Wherever cobble reports the next scheduled backup or update check, it SHALL report the time with the UTC offset of the cobble timezone at that instant, so that every consumer resolves it to the same moment.

#### Scenario: Next run reported in a non-UTC timezone

- **WHEN** the cobble timezone is `Australia/Brisbane` and the update check is next due at 04:00 on 7 October 2026
- **THEN** its next run is reported as `2026-10-07T04:00:00+10:00`

#### Scenario: Next run reported across a daylight-saving change

- **WHEN** the cobble timezone observes daylight saving and the next run falls after the change
- **THEN** the reported offset is the one in force at the time of that run, not the current one
