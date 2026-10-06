## Purpose

Operator-editable, persisted configuration for how many backups cobble keeps and when it runs its scheduled backup and update-check activity, changeable from the running process without a restart.

## Requirements

### Requirement: Backup retention is configurable and persisted

Cobble SHALL allow an operator to set how many backups are retained, and SHALL persist that setting so it survives a restart.

#### Scenario: Operator changes retention

- **WHEN** an operator sets a new backup retention count
- **THEN** subsequent pruning uses the new count
- **AND** the setting is applied without restarting cobble

#### Scenario: Retention setting survives a restart

- **WHEN** cobble restarts after an operator has changed the retention count
- **THEN** the changed value is still in effect

#### Scenario: Retention applies uniformly

- **WHEN** backups are pruned
- **THEN** the same retention count governs scheduled backups and the mandatory pre-update backup alike, with no separate count for either

### Requirement: The backup schedule is independently configurable

Cobble SHALL allow an operator to configure the scheduled-backup trigger independently of the update-check trigger: whether it is enabled, a time of day, and a frequency of daily, weekly, or monthly. A weekly frequency SHALL include a day of the week and a monthly frequency SHALL include a day of the month.

#### Scenario: Operator sets a weekly backup schedule

- **WHEN** an operator configures the backup schedule as weekly on a chosen day and time
- **THEN** the scheduled backup next runs on that day and time
- **AND** it recurs weekly on that day thereafter

#### Scenario: Operator sets a monthly backup schedule

- **WHEN** an operator configures the backup schedule as monthly on a chosen day-of-month and time
- **THEN** the scheduled backup next runs on that day of the month
- **AND** a day-of-month that does not exist in a given month is scheduled on that month's last day instead of being skipped

#### Scenario: Backup schedule is disabled

- **WHEN** an operator disables the backup schedule
- **THEN** no scheduled backup occurs
- **AND** a manual backup and the mandatory pre-update backup are unaffected

### Requirement: The update-check schedule is independently configurable

Cobble SHALL allow an operator to configure the scheduled update-check trigger independently of the backup trigger, with the same enabled/time/frequency/day shape as the backup schedule.

#### Scenario: Operator sets a different cadence for updates than for backups

- **WHEN** an operator configures the update-check schedule with a different frequency or time than the backup schedule
- **THEN** each schedule's next run is computed independently
- **AND** each recurs on its own configured cadence

#### Scenario: Update-check schedule is disabled

- **WHEN** an operator disables the update-check schedule
- **THEN** no scheduled update check occurs
- **AND** an update can still be requested on demand

### Requirement: Settings changes apply without a restart

Cobble SHALL apply a change to backup retention, backup-schedule enablement, or either schedule's time/frequency/day to the running process immediately, without requiring a restart.

#### Scenario: Operator edits a schedule while cobble is running

- **WHEN** an operator changes a schedule's time, frequency, or day
- **THEN** the next scheduled run recomputes from the new configuration
- **AND** cobble does not need to be restarted for the change to take effect

### Requirement: The pre-update backup is not a configurable setting

The backup taken automatically before an update is applied is a safety mechanism the update's rollback depends on, not a schedule. Cobble SHALL NOT expose a setting to disable it.

#### Scenario: Operator looks for a way to disable the pre-update backup

- **WHEN** an operator views maintenance settings
- **THEN** the pre-update backup is presented as always occurring automatically before an update
- **AND** no control is offered to disable it

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
