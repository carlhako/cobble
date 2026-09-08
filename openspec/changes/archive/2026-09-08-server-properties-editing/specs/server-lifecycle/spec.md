## ADDED Requirements

### Requirement: Starting the server applies the saved configuration

Because the Bedrock server reads its configuration only at startup, any start of the managed server SHALL apply the configuration as saved at that moment, regardless of what caused the start.

#### Scenario: An operator restarts after saving configuration

- **WHEN** configuration is saved and the server is subsequently restarted by an operator
- **THEN** the server runs with the saved configuration

#### Scenario: The server is started by something other than an operator

- **WHEN** the server is started by automatic crash recovery, by an update, or by cobble starting
- **THEN** the server runs with the configuration as saved at that moment

#### Scenario: Configuration is saved while the server is stopped

- **WHEN** configuration is saved while the server is not running and the server is later started
- **THEN** the server runs with the saved configuration
