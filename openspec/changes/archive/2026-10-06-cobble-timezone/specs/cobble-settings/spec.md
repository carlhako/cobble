# Spec Delta

## Purpose

Operator-editable settings that belong to cobble itself rather than to the Bedrock server it manages, starting with the timezone that cobble's schedules run in. They are saved per cobble instance and applied without a restart.

## ADDED Requirements

### Requirement: The cobble timezone is configurable and persisted

Cobble SHALL allow an operator to set the timezone its scheduled activity runs in, as an IANA timezone name such as `Australia/Brisbane` or `UTC`, or to leave it unset. While it is unset, cobble SHALL use the host's local timezone. Cobble SHALL persist the setting so it survives a restart, and SHALL apply a change to the running process without a restart.

#### Scenario: Operator sets a timezone

- **WHEN** an operator sets the cobble timezone to `Australia/Brisbane`
- **THEN** the setting is saved
- **AND** cobble's schedules use `Australia/Brisbane` without cobble being restarted

#### Scenario: The setting survives a restart

- **WHEN** cobble restarts after an operator has set the timezone
- **THEN** the set timezone is still in effect

#### Scenario: Timezone left unset

- **WHEN** no timezone has been set
- **THEN** cobble uses the host's local timezone

#### Scenario: Operator clears the timezone

- **WHEN** an operator clears a previously set timezone
- **THEN** cobble returns to using the host's local timezone

### Requirement: Timezone names are validated

Cobble SHALL accept only timezone names it can resolve, and SHALL reject any other value with a message naming the problem, leaving the saved setting unchanged. Cobble SHALL be able to resolve IANA timezone names on a host that has no system timezone database.

#### Scenario: Unknown name

- **WHEN** an operator submits `Mars/Olympus_Mons` as the timezone
- **THEN** the change is rejected with a message that the timezone is not recognised
- **AND** the saved timezone is unchanged

#### Scenario: Host without a timezone database

- **WHEN** cobble runs on a host with no system timezone database and an operator submits `Europe/Berlin`
- **THEN** the timezone is accepted and used

### Requirement: Cobble settings are reported

Cobble SHALL report its settings through the programmatic interface. For the timezone, it SHALL report the timezone the operator set (or that none is set), the host's local timezone, and the effective timezone with its current UTC offset. The host's timezone SHALL be reported by IANA name when the host makes that name available, and otherwise by its UTC offset.

#### Scenario: Settings queried with a timezone set

- **WHEN** settings are requested and the operator has set `Australia/Brisbane` on a host whose local timezone is `UTC`
- **THEN** the set timezone is `Australia/Brisbane`, the host timezone is `UTC`, and the effective timezone is `Australia/Brisbane` at offset `+10:00`

#### Scenario: Settings queried with no timezone set

- **WHEN** settings are requested and no timezone has been set
- **THEN** the set timezone is reported as unset
- **AND** the effective timezone is the host's

### Requirement: Cobble settings belong to the instance

Cobble settings describe the cobble instance and its operator, not the managed server. A restore SHALL leave the destination's cobble settings as they were, whether the backup was captured locally or on another cobble instance.

#### Scenario: A backup from an instance in another timezone is restored

- **WHEN** a backup captured on an instance set to `Europe/London` is restored onto an instance set to `Australia/Brisbane`
- **THEN** the destination's timezone is still `Australia/Brisbane` after the restore
