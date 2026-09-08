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

### Requirement: The available server version is reported alongside the installed one

Cobble SHALL report the most recently observed available Bedrock version together with the installed version, so that an operator can see whether the server is behind.

#### Scenario: A newer version is known to be available

- **WHEN** a version check has found a version newer than the installed one
- **THEN** the status reports both the installed version and the available version

#### Scenario: The installed version is current

- **WHEN** a version check has found no newer version
- **THEN** the status reports that the installed version is current

#### Scenario: No check has succeeded

- **WHEN** no version check has yet succeeded
- **THEN** the status reports that the available version is unknown
- **AND** no error is raised

### Requirement: Update activity is reported

Cobble SHALL report when updates were last checked and last applied, the outcome of the most recent update, and when the next scheduled check will occur.

#### Scenario: Update state is queried

- **WHEN** status is requested
- **THEN** the time of the last update check, the outcome of the most recent update, and the next scheduled check are reported

#### Scenario: An update failed

- **WHEN** the most recent update failed
- **THEN** the status reports the failure, the version that was attempted, and the step at which it failed
- **AND** the output captured during the failed attempt is retrievable

#### Scenario: A version is being skipped

- **WHEN** the available version is one that previously failed an update
- **THEN** the status reports that this version is not being retried automatically

### Requirement: Backup activity is reported

Cobble SHALL report when a backup was last captured, whether it succeeded, when the next scheduled backup will occur, and the backups currently held.

#### Scenario: Backup state is queried

- **WHEN** status is requested
- **THEN** the time and outcome of the last backup and the next scheduled backup are reported

#### Scenario: Backups cannot be written

- **WHEN** backups are failing because the destination cannot be written
- **THEN** the status reports an unhealthy backup condition with the reason

#### Scenario: No backups have been captured

- **WHEN** status is requested and no backup has been captured
- **THEN** this is reported without error

### Requirement: Maintenance activity is reported separately from run state

Because an update or restore moves the server through several run states, cobble SHALL report whether a maintenance operation is in progress as a value distinct from the run state.

#### Scenario: An update is in progress

- **WHEN** an update is in progress
- **THEN** the status reports that an update is in progress
- **AND** the run state continues to report what the server process is doing

#### Scenario: A restore is in progress

- **WHEN** a restore is in progress
- **THEN** the status reports that a restore is in progress

#### Scenario: No maintenance is in progress

- **WHEN** no maintenance operation is in progress
- **THEN** the status reports no maintenance activity

#### Scenario: Maintenance progress is pushed to clients

- **WHEN** a maintenance operation begins, advances between steps, or ends
- **THEN** connected clients are notified without polling

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
