## ADDED Requirements

### Requirement: Pending configuration changes are reported

Cobble SHALL report whether saved server configuration differs from the configuration the running server was started with, and how many settings differ, so that the interface can present a restart-to-apply state without inspecting the configuration itself.

#### Scenario: Settings are waiting on a restart

- **WHEN** saved configuration differs from the configuration in effect
- **THEN** the status reports that configuration changes are pending
- **AND** the number of differing settings is reported

#### Scenario: Nothing is pending

- **WHEN** saved configuration matches the configuration in effect
- **THEN** the status reports no pending configuration changes

#### Scenario: The server is not running

- **WHEN** the managed server is not running
- **THEN** the status reports no pending configuration changes
- **AND** no error is raised

#### Scenario: Pending state is pushed to clients

- **WHEN** configuration is saved, or the server is started or restarted
- **THEN** connected clients are notified of the new pending state without polling
