## ADDED Requirements

### Requirement: Durable state is quiesced before it is captured

A backup captures cobble's state directory while cobble itself is still running, so state that cobble holds open may be written to during the capture. Cobble SHALL bring its own durable state to a self-consistent, restorable form before the capture reads it, so that including a file in a backup also means the restored copy is usable.

#### Scenario: A backup is captured while cobble holds durable state open

- **WHEN** a backup is captured
- **THEN** cobble's durable state is brought to a self-consistent form before the capture begins
- **AND** the captured copy is restorable without repair

#### Scenario: A captured backup is restored

- **WHEN** a backup is restored
- **THEN** cobble's durable state opens successfully
- **AND** it contains every record committed before the capture began

#### Scenario: Quiescing fails

- **WHEN** cobble's durable state cannot be brought to a consistent form
- **THEN** the backup fails rather than producing a capture that cannot be relied upon
- **AND** the failure is surfaced with its reason
