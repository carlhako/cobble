## ADDED Requirements

### Requirement: Cobble can query the server without disturbing the console

Cobble SHALL be able to send a command to the Bedrock server on its own behalf and consume the server's reply, without that command or its reply appearing in the console stream delivered to clients. This path is reserved for cobble's own queries; it SHALL NOT be reachable by a client.

#### Scenario: An internal query is not echoed

- **WHEN** cobble submits a command on its own behalf
- **THEN** the command does not appear in the console stream delivered to any client

#### Scenario: The reply to an internal query is consumed

- **WHEN** the server produces output in reply to a command cobble submitted on its own behalf
- **THEN** that reply is delivered to the requesting caller
- **AND** it does not appear in the console stream delivered to any client

#### Scenario: Server output unrelated to the query is unaffected

- **WHEN** the server produces output while an internal query is outstanding
- **THEN** output that is not the reply to that query is delivered to console clients as usual

#### Scenario: An internal query while the server is not running

- **WHEN** cobble submits an internal query and no server process is running
- **THEN** the query fails without being queued
- **AND** the console stream is unaffected

#### Scenario: The server does not reply

- **WHEN** the server produces no reply to an internal query within a bounded time
- **THEN** the query is abandoned and reported as failed
- **AND** the console and the Bedrock server are unaffected

#### Scenario: Clients cannot submit an internal query

- **WHEN** a client submits a console command
- **THEN** it is treated as an operator command and echoed, regardless of its content

## MODIFIED Requirements

### Requirement: Operators can send commands to the server

Cobble SHALL accept console commands from clients and relay them to the running Bedrock server's input. Commands cobble originates on its own behalf are not operator commands and are governed separately.

#### Scenario: Command is relayed

- **WHEN** a client submits a console command and the server is running
- **THEN** the command is delivered to the Bedrock server
- **AND** any output the server produces in response appears in the console stream

#### Scenario: Command submitted while the server is not running

- **WHEN** a client submits a console command and no server process is running
- **THEN** the command is not queued
- **AND** the request fails with an error stating the server is not running

#### Scenario: Submitted commands are visible in the stream

- **WHEN** a client submits a console command
- **THEN** the submitted command appears in the console stream delivered to all connected clients

#### Scenario: Commands cobble originates are not echoed

- **WHEN** cobble submits a command on its own behalf rather than on a client's
- **THEN** that command does not appear in the console stream

### Requirement: Command input is serialized

Because the Bedrock server has a single input channel, cobble SHALL serialize command delivery so that concurrently submitted commands are delivered whole and in a defined order. Commands cobble originates share that serialization with operator commands.

#### Scenario: Concurrent commands from multiple clients

- **WHEN** two clients submit commands at the same time
- **THEN** both commands are delivered to the server intact
- **AND** neither command's text is interleaved with the other's

#### Scenario: An operator command concurrent with an internal query

- **WHEN** a client submits a command while cobble has an internal query outstanding
- **THEN** both are delivered to the server intact and in a defined order
- **AND** neither command's text is interleaved with the other's
