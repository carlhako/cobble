## Purpose

Keeping the installed Bedrock server current: determining whether the vendor has published a newer release, applying it on a schedule or on demand without operator involvement, and guaranteeing that an update which does not produce a working server returns the installation to the state that preceded it.

## ADDED Requirements

### Requirement: Availability of a newer version is determined

Cobble SHALL determine whether the vendor's current Bedrock release differs from the installed version, and SHALL report the available version alongside the installed one.

#### Scenario: A newer version is published

- **WHEN** the vendor's current release differs from the installed version
- **THEN** the available version is reported as distinct from the installed version

#### Scenario: The installed version is current

- **WHEN** the vendor's current release matches the installed version
- **THEN** the installation is reported as up to date
- **AND** no update is attempted

#### Scenario: The vendor source cannot be reached

- **WHEN** the vendor source is unreachable or returns an unusable response during a check
- **THEN** the failure is recorded and surfaced
- **AND** no update is attempted
- **AND** the running server is unaffected

### Requirement: Updates are checked and applied on a recurring schedule

Cobble SHALL check for a newer version on a recurring schedule and SHALL apply an available update without operator involvement. The schedule SHALL be configurable and SHALL be capable of being disabled.

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

### Requirement: An update can be requested on demand

Cobble SHALL allow an operator to request a version check and update immediately, performing the same sequence as a scheduled run.

#### Scenario: Operator requests a check

- **WHEN** an operator requests an update check
- **THEN** the check is performed immediately
- **AND** an available update is applied using the same sequence as a scheduled run

#### Scenario: Request made while an update is in progress

- **WHEN** an update is requested and an update is already in progress
- **THEN** no second update begins
- **AND** the request fails with an error identifying the update already in progress

### Requirement: A new version is acquired before the server is interrupted

Cobble SHALL download and extract a new version while the existing server continues running, and SHALL NOT stop the server until acquisition has succeeded.

#### Scenario: Acquisition succeeds

- **WHEN** a new version is downloaded and extracted as part of an update
- **THEN** the running server has not been stopped at any point during acquisition

#### Scenario: Acquisition fails

- **WHEN** the download or extraction of a new version fails
- **THEN** the update is abandoned
- **AND** the server has not been stopped
- **AND** the active version is unchanged
- **AND** the failure is recorded and surfaced

### Requirement: An update captures a verified backup before changing the active version

Cobble SHALL capture a backup after stopping the server and SHALL verify that backup before the active version is changed. An update SHALL NOT proceed on an unverifiable backup.

#### Scenario: Backup is captured and verified

- **WHEN** the pre-update backup is captured and verifies successfully
- **THEN** the update proceeds to change the active version

#### Scenario: Backup cannot be captured or does not verify

- **WHEN** the pre-update backup fails or cannot be verified
- **THEN** the active version is not changed
- **AND** the previously active version is started again
- **AND** the failure is recorded and surfaced

### Requirement: An update refuses to proceed from an unclean shutdown

Because state produced by a forcible termination cannot be trusted as a rollback point, cobble SHALL abandon an update when the shutdown preceding it was recorded as unclean.

#### Scenario: The pre-update shutdown required forcible termination

- **WHEN** the shutdown performed as part of an update is recorded as unclean
- **THEN** the update is abandoned before the active version is changed
- **AND** the previously active version is started again
- **AND** the reason is recorded and surfaced

### Requirement: A newly activated version must signal readiness to be accepted

Cobble SHALL treat an update as successful only when the newly activated version signals readiness and remains running. Activation alone SHALL NOT be treated as success.

#### Scenario: The new version becomes ready

- **WHEN** the newly activated version signals readiness within the readiness timeout
- **AND** it remains running for the grace period following readiness
- **THEN** the update is recorded as successful

#### Scenario: The new version never signals readiness

- **WHEN** the newly activated version does not signal readiness within the readiness timeout
- **THEN** the update is treated as failed

#### Scenario: The new version exits shortly after becoming ready

- **WHEN** the newly activated version signals readiness but exits within the grace period that follows
- **THEN** the update is treated as failed

### Requirement: A failed update is rolled back automatically

When an update is treated as failed, cobble SHALL restore the previous version and the world captured before the update, without operator action.

#### Scenario: Rollback after a failed update

- **WHEN** an update is treated as failed
- **THEN** the previously active version is made active again
- **AND** the world is restored from the backup captured before the update
- **AND** the previous version is started
- **AND** no operator action is required

#### Scenario: World is restored even when the new version never became ready

- **WHEN** a rollback occurs and the failed version never signalled readiness
- **THEN** the world is still restored from the pre-update backup
- **AND** the world state left on disk by the failed version is not retained as authoritative

#### Scenario: Rollback restores service

- **WHEN** a rollback completes and the previous version signals readiness
- **THEN** the server is reported as running the previous version
- **AND** the failed update is reported

#### Scenario: Rollback itself fails

- **WHEN** the previous version cannot be started after a rollback attempt
- **THEN** cobble ceases further automatic recovery attempts
- **AND** no further automatic change is made to the installation
- **AND** the failure is surfaced as requiring operator intervention

### Requirement: A version that fails an update is not retried automatically

Cobble SHALL record a version that failed an update and SHALL NOT attempt that same version again automatically, so that a defective release does not produce a repeating outage.

#### Scenario: The same version remains the vendor's current release

- **WHEN** a scheduled check finds that the current vendor release is a version that previously failed an update
- **THEN** no update is attempted
- **AND** the reason is reported

#### Scenario: A different version is published

- **WHEN** the vendor publishes a version other than the one that previously failed
- **THEN** an update to that version is attempted normally

#### Scenario: Operator clears the record

- **WHEN** an operator clears the record of a failed version
- **THEN** that version may be attempted again

#### Scenario: Files from the failed version are retained

- **WHEN** a version has failed an update
- **THEN** its installed files are retained rather than removed

### Requirement: Update outcomes and failure diagnostics are retained

Cobble SHALL record the outcome of each update and SHALL retain, for a failed update, the version attempted, the step at which it failed, and the server output captured during the attempt.

#### Scenario: A failed update is recorded

- **WHEN** an update fails
- **THEN** the version attempted, the failing step, and the output captured from the attempt are retained
- **AND** they are retrievable without consulting the host's system logs

#### Scenario: A successful update is recorded

- **WHEN** an update succeeds
- **THEN** the version installed and the time of the update are recorded

#### Scenario: Records survive cobble restart

- **WHEN** cobble restarts after recording an update outcome
- **THEN** that record remains retrievable

### Requirement: Superseded versions are pruned but the rollback source is retained

After a successful update, cobble SHALL retain the version it replaced so that a later rollback is possible, and SHALL remove installations older than that.

#### Scenario: Pruning after a successful update

- **WHEN** an update succeeds
- **THEN** the version that was replaced is retained
- **AND** installations older than the replaced version are removed

#### Scenario: The rollback source is never pruned

- **WHEN** pruning is performed
- **THEN** the installation required to roll back the most recent update is not removed
