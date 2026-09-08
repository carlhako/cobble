## ADDED Requirements

### Requirement: Gamerule activity is reported

Cobble SHALL report whether the gamerule set for the active world is current, when it was last read, and any adoption, repair, or application of defaults that the operator has not yet acknowledged.

#### Scenario: Gamerule state is queried

- **WHEN** status is requested
- **THEN** the active world's name, whether its gamerule set is live or recorded, and when it was last read are reported

#### Scenario: A divergence was adopted

- **WHEN** cobble has adopted a gamerule changed outside the interface and the operator has not acknowledged it
- **THEN** the status reports the adoption, naming each rule and the value adopted

#### Scenario: A divergence was repaired after a restore

- **WHEN** cobble has re-applied recorded gamerules following a restore and the operator has not acknowledged it
- **THEN** the status reports the repair, naming each rule and the value re-applied

#### Scenario: Defaults were applied to a new world

- **WHEN** cobble has applied preferred defaults to a world observed for the first time and the operator has not acknowledged it
- **THEN** the status reports the application, naming the world and each rule set

#### Scenario: The operator acknowledges a report

- **WHEN** the operator acknowledges a reported adoption, repair, or application
- **THEN** it is no longer reported in status
- **AND** the recorded gamerule values are unchanged

#### Scenario: Nothing has happened

- **WHEN** status is requested and no unacknowledged gamerule activity exists
- **THEN** no adoption, repair, or application is reported
