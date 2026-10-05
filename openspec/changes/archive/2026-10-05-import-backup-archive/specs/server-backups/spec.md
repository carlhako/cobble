# Spec Delta

## ADDED Requirements

### Requirement: A restore keeps the destination's instance-local state

Some of cobble's durable state describes the host cobble runs on rather than the server it manages. Cobble SHALL leave that instance-local state as it was on the destination when a backup is restored, whether the backup was captured locally or on another cobble instance. Instance-local state SHALL include cobble's own self-upgrade requests and results, its release-check record, its record of the last server shutdown, its record of whether the server should be running, its layout-migration record, its world-import staging area, and its backup history.

#### Scenario: A backup from another instance is restored

- **WHEN** a backup captured on a different cobble instance is restored
- **THEN** the destination's backup history is unchanged and lists only backups taken on the destination
- **AND** no self-upgrade of cobble is requested or reported as a result of the restore
- **AND** the destination's last-shutdown and layout-migration records are unchanged

#### Scenario: Server state in the backup is restored

- **WHEN** a backup is restored
- **THEN** player history, maintenance settings, update state, gamerule records, and access records match those in the backup

### Requirement: Cobble runs on the restored state after a restore

Because cobble holds parts of its durable state open or in memory while it runs, cobble SHALL, after a restore completes, restart its own process so that everything it reports and acts on comes from the restored state, and SHALL return the server to the run state it had before the restore.

#### Scenario: A restore completes while the server was running

- **WHEN** a restore completes and the server was running before it began
- **THEN** cobble restarts
- **AND** once cobble is back, the server is running

#### Scenario: A restore completes while the server was stopped

- **WHEN** a restore completes and the server was stopped before it began
- **THEN** cobble restarts
- **AND** once cobble is back, the server is not running

#### Scenario: Cobble's own shutdown does not overwrite restored state

- **WHEN** cobble restarts after a restore
- **THEN** no state cobble held from before the restore is written over the restored state

#### Scenario: Restored player history is used after a restore

- **WHEN** player activity occurs after a restore has completed
- **THEN** it is recorded in the restored player history
- **AND** it is still present after cobble's next restart

#### Scenario: The operator's interface reconnects

- **WHEN** an operator's interface requested the restore and cobble restarts
- **THEN** the outcome of the restore is reported to the interface before cobble restarts
- **AND** the interface resumes showing live state once cobble is back, without the operator reloading it

#### Scenario: A restore fails

- **WHEN** a restore fails partway through
- **THEN** the failure is reported as it is today
- **AND** cobble returns the server to its previous run state without requiring a restart to do so
