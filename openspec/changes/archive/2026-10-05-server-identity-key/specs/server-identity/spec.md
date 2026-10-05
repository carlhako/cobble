# Spec Delta

## Purpose

Keeps the Bedrock server's NetherNet identity stable across restarts by saving the running identity key once, and shows the operator whether it is saved.

## ADDED Requirements

### Requirement: The saved identity state is reported

cobble SHALL report whether a saved server identity key exists, as part of the network view. The state SHALL be determined from the key file in the server's working directory (`keys/server_identity_key.pem`) without sending a command to the server, so it is available whether the server is running or stopped. The report SHALL say whether the server is running, so the interface can tell whether a save is possible now.

#### Scenario: No key is saved

- **WHEN** the network view is read and `keys/server_identity_key.pem` does not exist
- **THEN** the identity is reported as not saved

#### Scenario: A key is saved

- **WHEN** the network view is read and `keys/server_identity_key.pem` exists
- **THEN** the identity is reported as saved

#### Scenario: The server is stopped

- **WHEN** the network view is read while the server is stopped
- **THEN** the identity state is still reported from the file
- **AND** the report says that a save is not possible until the server runs

### Requirement: The running identity is saved once when none is saved

When the server becomes ready and no saved identity key exists, cobble SHALL instruct the server to save its currently running identity. It SHALL NOT generate a key of its own, so players who already trust the running identity keep trusting it. cobble SHALL NOT issue the save when a key file already exists, including one the operator placed there. The command and its reply SHALL NOT be echoed to console clients. A failed or unanswered save SHALL be logged, SHALL NOT stop or restart the server, and SHALL leave the identity reported as not saved. The save SHALL be attempted regardless of the saved transport.

#### Scenario: First start without a key

- **WHEN** the server becomes ready and no key file exists
- **THEN** cobble saves the running identity
- **AND** the key file exists afterwards
- **AND** the identity is reported as saved

#### Scenario: A key already exists

- **WHEN** the server becomes ready and a key file already exists
- **THEN** cobble issues no save
- **AND** the key file is unchanged

#### Scenario: Later restarts keep the identity

- **WHEN** the server is restarted after the identity was saved
- **THEN** the server starts with the saved key
- **AND** cobble issues no save

#### Scenario: The save fails

- **WHEN** the server replies that the save failed, or does not reply in time
- **THEN** the failure is logged
- **AND** the server keeps running
- **AND** the identity is reported as not saved

#### Scenario: The save is not shown on the console

- **WHEN** cobble saves the identity automatically
- **THEN** console clients see neither the command nor the server's reply to it

### Requirement: The running identity can be saved on request

cobble SHALL accept a request to save the running identity. The request SHALL be refused when the server is not running, and while a maintenance operation is in progress, with the same errors as other server writes. When a key file already exists, the request SHALL succeed without issuing a save and SHALL leave the file unchanged. Otherwise cobble issues the save and returns the resulting identity state, or an error naming the server's failure reply.

#### Scenario: Manual save succeeds

- **WHEN** the operator requests a save while the server runs and no key is saved
- **THEN** the running identity is saved
- **AND** the response reports the identity as saved

#### Scenario: Manual save while stopped

- **WHEN** the operator requests a save while the server is stopped
- **THEN** the request is refused with the not-running error
- **AND** no file is written

#### Scenario: Manual save during maintenance

- **WHEN** the operator requests a save during a maintenance operation
- **THEN** the request is refused with the maintenance error

#### Scenario: Manual save when a key exists

- **WHEN** the operator requests a save and a key file already exists
- **THEN** no save is issued
- **AND** the response reports the identity as saved

### Requirement: A saved identity survives updates and travels with backups

The key file SHALL live in the server's mutable data, never in a version's vendor payload. Installing or activating a Bedrock version SHALL NOT remove or replace it. A backup SHALL capture it, and restoring that backup SHALL restore it.

#### Scenario: Bedrock update

- **WHEN** a Bedrock update activates a new version while a key is saved
- **THEN** the key file is unchanged after the update

#### Scenario: Backup and restore

- **WHEN** a backup is captured while a key is saved, and later restored
- **THEN** the restored installation has the same key file

#### Scenario: Restoring a backup without a key

- **WHEN** a backup captured before any key was saved is restored
- **THEN** no key file exists after the restore
- **AND** the next time the server becomes ready, the running identity is saved

### Requirement: The network section shows the identity state

The network section SHALL show the server identity state under NetherNet, with a short explanation that an identity which is not saved changes on every restart, and that players may then have to accept the server again. While the server is running and no key is saved, the section SHALL offer an action that saves the running identity. While the server is stopped and no key is saved, it SHALL say that the identity will be saved at the next start. The action SHALL NOT be offered during maintenance. Under RakNet the identity state SHALL NOT be shown.

#### Scenario: Identity saved

- **WHEN** the operator opens the network section under NetherNet and a key is saved
- **THEN** the identity is shown as saved
- **AND** no save action is offered

#### Scenario: Identity not saved, server running

- **WHEN** no key is saved and the server is running
- **THEN** the identity is shown as not saved, with the explanation
- **AND** an action to save the current identity is offered

#### Scenario: Saving from the section

- **WHEN** the operator uses the save action and it succeeds
- **THEN** the section shows the identity as saved without a page reload

#### Scenario: Save fails from the section

- **WHEN** the operator uses the save action and the server reports a failure
- **THEN** the section shows the failure reason
- **AND** the identity is still shown as not saved

#### Scenario: Identity not saved, server stopped

- **WHEN** no key is saved and the server is stopped
- **THEN** the section says the identity will be saved at the next start
- **AND** no save action is offered

#### Scenario: RakNet layout

- **WHEN** the saved transport is `raknet`
- **THEN** the identity state is not shown
