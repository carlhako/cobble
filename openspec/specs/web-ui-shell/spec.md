## Purpose

The web interface's application shell — how it is served, how it stays connected to live server state, and the navigation and layout foundation that configuration, gamerule, and player screens are later added into.

## Requirements

### Requirement: The web interface is served by the application

Cobble SHALL serve the web interface and its programmatic interface from a single service on a single port, requiring no separate web server.

#### Scenario: Interface is reachable

- **WHEN** an operator opens cobble's address in a browser
- **THEN** the web interface is served

#### Scenario: Client-side routes are served directly

- **WHEN** an operator opens or reloads a page at a sub-path of the interface
- **THEN** the interface loads at that location
- **AND** no not-found error is returned for a valid interface route

### Requirement: All state-changing operations go through the programmatic interface

Every operation that changes server or cobble state SHALL be performed through the programmatic interface. The web interface SHALL have no privileged path that bypasses it.

#### Scenario: Interface performs an action

- **WHEN** the web interface performs any state-changing action
- **THEN** it is carried out as a call to the programmatic interface

#### Scenario: A non-browser client performs the same action

- **WHEN** a client other than the web interface makes the same call
- **THEN** the same behavior occurs
- **AND** no capability is available only to the web interface

### Requirement: Live server state is reflected without user action

The web interface SHALL reflect run state, console output, and online players as they change, without the operator refreshing or re-navigating.

#### Scenario: Server state changes while the interface is open

- **WHEN** the managed server's run state changes
- **THEN** the displayed state updates without operator action

#### Scenario: Output arrives while the console is open

- **WHEN** the server produces console output
- **THEN** it appears in the open console view

### Requirement: The interface recovers from lost connections

The web interface SHALL detect when its live connection to the service is lost, indicate this to the operator, and restore the connection automatically when possible.

#### Scenario: Connection is lost

- **WHEN** the live connection to the service is interrupted
- **THEN** the interface indicates that it is disconnected
- **AND** stale state is not presented as current

#### Scenario: Connection is restored

- **WHEN** the service becomes reachable again
- **THEN** the interface reconnects without operator action
- **AND** the displayed state is brought up to date

#### Scenario: Service is restarted

- **WHEN** the cobble service is restarted while the interface is open
- **THEN** the interface reconnects once the service is available again

### Requirement: Server control is available from the interface

The web interface SHALL allow an operator to start, stop, and restart the managed server, and SHALL reflect which of those actions are currently possible.

#### Scenario: Controls reflect the current state

- **WHEN** the server is running
- **THEN** stopping and restarting are offered
- **AND** starting is not offered as an available action

#### Scenario: An action is in progress

- **WHEN** a lifecycle action is in progress
- **THEN** the interface indicates the transition
- **AND** conflicting actions are not offered

#### Scenario: An action fails

- **WHEN** a requested lifecycle action fails
- **THEN** the interface reports the failure and the reason

### Requirement: Console interaction is available from the interface

The web interface SHALL present console output and allow an operator to submit commands when the server is running.

#### Scenario: Operator submits a command

- **WHEN** an operator submits a command from the console view and the server is running
- **THEN** the command is sent
- **AND** the command and any resulting output appear in the console view

#### Scenario: Server is not running

- **WHEN** the server is not running
- **THEN** command submission is not offered as available

### Requirement: The shell accommodates screens added by later work

The interface SHALL provide navigation and layout structure into which additional sections can be added without restructuring the shell.

#### Scenario: A new section is added

- **WHEN** a new section is added to the interface
- **THEN** it appears in navigation
- **AND** existing sections are unaffected
