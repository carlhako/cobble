# Spec Delta

## MODIFIED Requirements

### Requirement: A restore keeps the destination's instance-local state

Some of cobble's durable state describes the host cobble runs on rather than the server it manages. Cobble SHALL leave that instance-local state as it was on the destination when a backup is restored, whether the backup was captured locally or on another cobble instance. Instance-local state SHALL include cobble's own self-upgrade requests and results, its release-check record, its record of the last server shutdown, its record of whether the server should be running, its layout-migration record, its world-import staging area, its backup history, and its cobble settings, including the cobble timezone.

#### Scenario: A backup from another instance is restored

- **WHEN** a backup captured on a different cobble instance is restored
- **THEN** the destination's backup history is unchanged and lists only backups taken on the destination
- **AND** no self-upgrade of cobble is requested or reported as a result of the restore
- **AND** the destination's last-shutdown and layout-migration records are unchanged
- **AND** the destination's cobble timezone is unchanged

#### Scenario: Server state in the backup is restored

- **WHEN** a backup is restored
- **THEN** player history, maintenance settings, update state, gamerule records, and access records match those in the backup
