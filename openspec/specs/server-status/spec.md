## Purpose

The observable state of the managed Bedrock server — whether it is running, which version is installed, how long it has been up, and who is currently online — presented as a single coherent view for operators and for the web interface.

## Requirements

### Requirement: Run state is exposed

Cobble SHALL expose the current run state of the managed server, distinguishing at minimum: stopped, starting, running, stopping, crashed, and failed.

#### Scenario: State is queryable at any time

- **WHEN** the run state is requested
- **THEN** the current state is returned
- **AND** a state is returned even when no server process exists

#### Scenario: State reflects transitions

- **WHEN** the server moves between lifecycle states
- **THEN** the exposed run state reflects the new state

### Requirement: Status changes are pushed to clients

Cobble SHALL deliver status changes to connected clients as they occur, so that the interface reflects the server's state without polling.

#### Scenario: Server becomes ready

- **WHEN** the server transitions to running
- **THEN** connected clients are notified of the new state

#### Scenario: Server crashes while clients are connected

- **WHEN** the server exits unexpectedly
- **THEN** connected clients are notified that the server is no longer running

### Requirement: Installed server version is reported

Cobble SHALL report the version of the Bedrock server that is currently installed.

#### Scenario: Version reported when installed

- **WHEN** a Bedrock installation is present
- **THEN** its version is reported

#### Scenario: No installation present

- **WHEN** no Bedrock installation is present
- **THEN** the status reports that no version is installed
- **AND** no error is raised

### Requirement: Uptime is reported

Cobble SHALL report how long the managed server has been running, measured from when it became ready.

#### Scenario: Uptime while running

- **WHEN** the server is running
- **THEN** the elapsed time since it became ready is reported

#### Scenario: Uptime while not running

- **WHEN** the server is not running
- **THEN** no uptime is reported

#### Scenario: Uptime resets on restart

- **WHEN** the server is restarted
- **THEN** the reported uptime is measured from the new readiness, not the previous one

### Requirement: Currently online players are reported

Cobble SHALL report which players are currently connected, derived from observed player events.

#### Scenario: Player joins

- **WHEN** a player connects
- **THEN** that player appears in the online players list

#### Scenario: Player leaves

- **WHEN** a connected player disconnects
- **THEN** that player no longer appears in the online players list

#### Scenario: Server stops

- **WHEN** the server stops for any reason
- **THEN** the online players list is empty

#### Scenario: Cobble started while the server was already running

- **WHEN** cobble cannot account for the full connection history of the running server
- **THEN** the online players list reports what it has observed
- **AND** the status indicates that the list may be incomplete

### Requirement: Most recent shutdown cleanliness is visible in status

Cobble SHALL surface whether the most recent shutdown was clean, so that an operator can see that the server was terminated forcibly.

#### Scenario: Prior shutdown was unclean

- **WHEN** the most recent shutdown required forcible termination
- **THEN** the status reports that the last shutdown was unclean
