## MODIFIED Requirements

### Requirement: The gamerule set is recorded per world

Because gamerules belong to a world and not to the server, cobble SHALL keep a record of the gamerule set for each world it has observed, identified by that world's name. Cobble SHALL keep the record current with its own changes, so that a change made through cobble is never later reported as made outside cobble.

#### Scenario: Each world keeps its own record

- **WHEN** cobble has observed gamerules on more than one world
- **THEN** each world's record is kept separately
- **AND** changing the active world does not alter another world's record

#### Scenario: The record is sampled at start and before stop

- **WHEN** the server becomes ready, or the gamerule set is read live from the running server
- **THEN** the gamerule set in effect is recorded against the active world
- **AND** when cobble stops the server, the record already holds the last set cobble read or wrote, with no separate read at stop

#### Scenario: A change made through cobble updates the record

- **WHEN** a rule is changed through cobble while the server is running and the re-read confirms the new value
- **THEN** the re-read set becomes the active world's record

#### Scenario: A change made through cobble is not reported after a restart

- **WHEN** a rule is changed through cobble while the server is running, and the server is then restarted or cobble itself is restarted or upgraded
- **THEN** no report that a gamerule was changed outside cobble is produced for that change

### Requirement: A divergence from the record is adopted and reported

When the live gamerule set differs from cobble's record and cobble did not cause the difference, the change was made by an operator in game and SHALL be treated as intended: cobble SHALL adopt the live value as the new record and report that it did so. A divergence SHALL be detected whenever the live set is read, at readiness or while the server is running.

#### Scenario: A rule was changed in game

- **WHEN** the live value of a rule differs from the record and cobble did not cause it
- **THEN** the live value replaces the recorded one
- **AND** the change is reported to the operator, naming the rule and its new value

#### Scenario: A change in game is reported while the server runs

- **WHEN** a rule is changed in game and the gamerule set is then read live, before any restart
- **THEN** the change is adopted and reported at that read
- **AND** it is not reported a second time at the next readiness

#### Scenario: Adoption never reverts the change

- **WHEN** cobble adopts a divergence
- **THEN** the value on the running server is left as the operator set it

#### Scenario: No divergence

- **WHEN** the live gamerule set matches the record
- **THEN** nothing is reported
