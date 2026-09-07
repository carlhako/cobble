## Purpose

Supervision of the Bedrock Dedicated Server process: starting it, stopping it without risking world corruption, restarting it, and detecting when it fails on its own. This is the capability every other part of cobble depends on.

## Requirements

### Requirement: Single supervised server instance

Cobble SHALL supervise exactly one Bedrock Dedicated Server process. It SHALL NOT be possible for two managed server processes to run concurrently against the same installation.

#### Scenario: Start requested while already running

- **WHEN** a start is requested and the server is already running
- **THEN** no second process is spawned
- **AND** the request fails with an error identifying the server as already running

#### Scenario: Start requested while a stop is in progress

- **WHEN** a start is requested and the server is in the process of stopping
- **THEN** no process is spawned
- **AND** the request fails with an error identifying the in-progress transition

### Requirement: Starting the server

Cobble SHALL start the Bedrock server on request and report the outcome. The server SHALL NOT be considered started until it signals readiness; process spawn alone is insufficient.

#### Scenario: Successful start

- **WHEN** a start is requested and the server is stopped
- **THEN** the Bedrock server process is spawned
- **AND** the run state becomes `starting`
- **AND** the run state becomes `running` once the readiness signal is observed

#### Scenario: Server fails to become ready

- **WHEN** the server is started but no readiness signal is observed within the readiness timeout
- **THEN** the run state becomes `failed`
- **AND** the captured output leading to the failure is retained and retrievable

#### Scenario: No Bedrock installation present

- **WHEN** a start is requested and no Bedrock installation is present
- **THEN** no process is spawned
- **AND** the request fails with an error stating that no installation exists

### Requirement: Clean shutdown

Cobble SHALL stop the server by issuing the Bedrock `stop` console command and waiting for the process to exit on its own, so that the world is flushed to disk before termination. Cobble SHALL NOT terminate the process by signal before the configured shutdown timeout has elapsed.

#### Scenario: Server exits cleanly within the timeout

- **WHEN** a stop is requested and the server exits before the shutdown timeout elapses
- **THEN** the run state becomes `stopped`
- **AND** the shutdown is recorded as clean

#### Scenario: Server does not exit within the timeout

- **WHEN** a stop is requested and the server has not exited when the shutdown timeout elapses
- **THEN** the process is forcibly terminated
- **AND** the run state becomes `stopped`
- **AND** the shutdown is recorded as unclean

#### Scenario: Shutdown timeout is configurable

- **WHEN** an operator configures a shutdown timeout
- **THEN** that value is used for subsequent stop operations
- **AND** the default value is at least 120 seconds

### Requirement: Unclean shutdowns are recorded and observable

Cobble SHALL record whether each shutdown was clean or unclean, and SHALL expose the cleanliness of the most recent shutdown. This record exists so that later mechanisms can refuse to treat state produced by an unclean shutdown as trustworthy.

#### Scenario: Unclean shutdown is surfaced

- **WHEN** a shutdown required forcible termination
- **THEN** the most recent shutdown is reported as unclean
- **AND** the record includes when it occurred

#### Scenario: Record survives cobble restart

- **WHEN** cobble restarts after recording an unclean shutdown
- **THEN** the record of that unclean shutdown remains retrievable

### Requirement: Restarting the server

Cobble SHALL support restarting the server as a single operation that performs a clean shutdown followed by a start.

#### Scenario: Restart from running

- **WHEN** a restart is requested and the server is running
- **THEN** the server is stopped using the clean shutdown behavior
- **AND** the server is started again
- **AND** the run state ends as `running` if startup succeeds

#### Scenario: Restart when stopped

- **WHEN** a restart is requested and the server is stopped
- **THEN** the server is started
- **AND** no error is raised for the absence of a running process

### Requirement: Unexpected server exit is detected

Cobble SHALL detect when the Bedrock server process exits without having been asked to stop, and SHALL distinguish this from an operator-requested stop.

#### Scenario: Server crashes

- **WHEN** the server process exits and no stop was requested
- **THEN** the run state becomes `crashed`
- **AND** the exit code and the output preceding the exit are retained

#### Scenario: Crash is distinguishable from a requested stop

- **WHEN** the server process exits after a stop was requested
- **THEN** the run state becomes `stopped` rather than `crashed`

### Requirement: Crash recovery does not loop indefinitely

Cobble SHALL be able to restart a crashed server automatically, and SHALL stop attempting restarts when failures repeat, leaving the failure visible rather than retrying forever.

#### Scenario: Automatic restart after a crash

- **WHEN** the server crashes and automatic restart is enabled
- **THEN** cobble attempts to start the server again

#### Scenario: Repeated crashes halt recovery

- **WHEN** the server crashes repeatedly beyond the configured failure threshold
- **THEN** cobble stops attempting automatic restarts
- **AND** the run state reports that recovery was abandoned
- **AND** an operator can still request a start manually

### Requirement: Server lifecycle follows cobble's own lifecycle

The managed server SHALL be started when cobble starts, if it was running when cobble last stopped, and SHALL be shut down cleanly when cobble is asked to terminate.

#### Scenario: Cobble is asked to terminate

- **WHEN** cobble receives a termination signal while the server is running
- **THEN** the server is stopped using the clean shutdown behavior before cobble exits

#### Scenario: Cobble starts after a host reboot

- **WHEN** cobble starts and the server was running when cobble last stopped
- **THEN** the server is started automatically
