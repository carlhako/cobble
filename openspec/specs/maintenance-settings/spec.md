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
