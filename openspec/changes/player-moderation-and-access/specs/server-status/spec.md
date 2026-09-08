## ADDED Requirements

### Requirement: Access state is reported

Cobble SHALL report whether the running server is enforcing the allowlist, how that compares to the saved configuration, and how many players are currently banned, so that the standing access posture is visible without opening a section.

#### Scenario: Status is requested while the server runs

- **WHEN** status is requested and the managed server is running
- **THEN** whether the allowlist is being enforced is reported
- **AND** the number of recorded bans is reported

#### Scenario: The enforcement state has not been observed

- **WHEN** status is requested and cobble has not observed the running server's enforcement state
- **THEN** the enforcement state is reported as unknown rather than guessed

#### Scenario: Enforcement differs from the saved configuration

- **WHEN** the enforcement in effect differs from the saved configuration
- **THEN** the disagreement is reported

#### Scenario: The server is not running

- **WHEN** status is requested and the managed server is not running
- **THEN** the enforcement state that the saved configuration will apply at the next start is reported
- **AND** it is distinguishable from an observed live state

#### Scenario: Enforcement changes

- **WHEN** allowlist enforcement changes while clients are connected
- **THEN** an updated status is pushed to them
