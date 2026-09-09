## ADDED Requirements

### Requirement: The allowlist enforcement setting is applied to the running server

Because the Bedrock server accepts a change to allowlist enforcement without a restart, and because that change does not otherwise reach the configuration file, cobble SHALL apply this one setting to the running server as well as saving it.

#### Scenario: The setting is changed while the server runs

- **WHEN** the allowlist enforcement setting is changed while the managed server is running
- **THEN** the value is persisted to the server's configuration
- **AND** the running server is instructed to enforce or stop enforcing the allowlist to match

#### Scenario: The setting is changed while the server is stopped

- **WHEN** the allowlist enforcement setting is changed while the managed server is not running
- **THEN** the value is persisted
- **AND** it takes effect when the server next starts

#### Scenario: The running server is instructed but the file write fails

- **WHEN** the setting cannot be persisted
- **THEN** the running server is not instructed to change enforcement
- **AND** the failure is reported

## MODIFIED Requirements

### Requirement: Saved configuration that differs from the running server is reported

Because the Bedrock server reads its configuration only when it starts, cobble SHALL report which saved settings differ from those the running server was started with, so that an operator can see what a restart would apply. The allowlist enforcement setting is excepted: it is applied to the running server when saved, so it is never pending on that account.

#### Scenario: A setting is changed while the server runs

- **WHEN** a setting is changed and the managed server is running with a different value
- **THEN** that setting is reported as pending
- **AND** both the saved value and the value in effect are reported

#### Scenario: The allowlist enforcement setting is changed while the server runs

- **WHEN** the allowlist enforcement setting is changed while the managed server is running
- **THEN** it is not reported as pending
- **AND** the enforcement state in effect matches the saved value

#### Scenario: Allowlist enforcement was changed outside cobble

- **WHEN** allowlist enforcement is changed by any means other than cobble while the server is running
- **THEN** the difference between the enforcement in effect and the saved setting is reported
- **AND** the report identifies which value is in effect

#### Scenario: No settings differ

- **WHEN** the saved configuration matches the configuration in effect
- **THEN** no settings are reported as pending

#### Scenario: The server is restarted

- **WHEN** the managed server is restarted after settings were changed
- **THEN** those settings are no longer reported as pending

#### Scenario: The configuration is changed outside cobble

- **WHEN** the configuration is changed by any means other than cobble while the server is running
- **THEN** the differing settings are reported as pending
- **AND** the report does not depend on cobble having performed the change

#### Scenario: The server is not running

- **WHEN** the managed server is not running
- **THEN** no settings are reported as pending
- **AND** no error is raised

#### Scenario: A comment or reordering change is made

- **WHEN** the configuration file changes without any effective value changing
- **THEN** no settings are reported as pending
