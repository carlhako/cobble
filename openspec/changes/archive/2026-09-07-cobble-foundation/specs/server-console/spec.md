## Purpose

Bidirectional console access to the Bedrock server: streaming its output to connected clients in real time and relaying operator commands to its input, which together replace the need for an SSH session.

## ADDED Requirements

### Requirement: Console output is streamed to clients

Cobble SHALL stream Bedrock server output to connected clients as it is produced, without requiring the client to poll.

#### Scenario: Output appears while connected

- **WHEN** a client is connected to the console stream and the server produces output
- **THEN** that output is delivered to the client without the client issuing a further request

#### Scenario: Multiple concurrent clients

- **WHEN** more than one client is connected to the console stream
- **THEN** each connected client receives the same output

#### Scenario: Client connects while the server is stopped

- **WHEN** a client connects to the console stream and no server process is running
- **THEN** the connection succeeds
- **AND** the client receives output once a server is started

### Requirement: Recent console history is available on connect

Cobble SHALL retain a bounded buffer of recent console output and SHALL deliver it to a client when that client connects, so that a newly opened console is not blank.

#### Scenario: History delivered on connect

- **WHEN** a client connects to the console stream and prior output exists
- **THEN** the retained recent output is delivered before subsequent live output

#### Scenario: Buffer is bounded

- **WHEN** the server has produced more output than the retention limit
- **THEN** memory use remains bounded
- **AND** the most recent output is retained in preference to older output

#### Scenario: History survives a server restart

- **WHEN** the Bedrock server is restarted while cobble continues running
- **THEN** console output from before the restart remains in the retained history
- **AND** the restart is distinguishable within the stream

### Requirement: Operators can send commands to the server

Cobble SHALL accept console commands from clients and relay them to the running Bedrock server's input.

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

### Requirement: Command input is serialized

Because the Bedrock server has a single input channel, cobble SHALL serialize command delivery so that concurrently submitted commands are delivered whole and in a defined order.

#### Scenario: Concurrent commands from multiple clients

- **WHEN** two clients submit commands at the same time
- **THEN** both commands are delivered to the server intact
- **AND** neither command's text is interleaved with the other's

### Requirement: Console streams recover from disconnection

Cobble SHALL tolerate clients disconnecting and reconnecting at any time without affecting the managed server or other clients.

#### Scenario: Client disconnects

- **WHEN** a connected console client disconnects
- **THEN** the Bedrock server is unaffected
- **AND** other connected clients continue to receive output

#### Scenario: Client reconnects

- **WHEN** a client reconnects to the console stream after disconnecting
- **THEN** the connection succeeds
- **AND** the retained recent output is delivered
