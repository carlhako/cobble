## Purpose

Operator-editable configuration of the Bedrock server: reading and writing `server.properties` as validated, typed settings, describing the worlds that back the level selection, and reporting which saved settings differ from those the running server was started with.

## Requirements

### Requirement: Server configuration is readable

Cobble SHALL expose the current contents of the Bedrock server's configuration as a set of settings, each with its key and current value. Settings that cobble recognises SHALL additionally carry their type, documented default, and permitted values or range. Settings present in the configuration that cobble does not recognise SHALL still be exposed with their key and value.

#### Scenario: Configuration is requested

- **WHEN** the server configuration is requested
- **THEN** every setting present in the configuration is returned with its current value

#### Scenario: A recognised setting is returned

- **WHEN** a returned setting is one cobble recognises
- **THEN** its type, documented default, and permitted values or range are included

#### Scenario: An unrecognised setting is present

- **WHEN** the configuration contains a setting cobble does not recognise
- **THEN** that setting is returned with its key and value
- **AND** it is identified as unrecognised
- **AND** no error is raised

#### Scenario: Configuration is requested while the server is stopped

- **WHEN** the configuration is requested and the managed server is not running
- **THEN** the configuration is returned

#### Scenario: A setting appears more than once

- **WHEN** the same key is assigned more than once in the configuration
- **THEN** the value reported is the one the Bedrock server would use

### Requirement: Server configuration is writable

Cobble SHALL accept changes to configuration settings and persist them, so that an operator can change how the server runs without shell access to the host.

#### Scenario: A setting is changed

- **WHEN** a valid new value is submitted for a setting
- **THEN** the value is persisted to the server's configuration
- **AND** a subsequent read reports the new value

#### Scenario: Several settings are changed together

- **WHEN** valid new values are submitted for several settings in one request
- **THEN** all of them are persisted
- **AND** either all changes are applied or none are

#### Scenario: An unrecognised setting is changed

- **WHEN** a new value is submitted for a setting cobble does not recognise
- **THEN** the value is persisted

#### Scenario: A setting is added

- **WHEN** a value is submitted for a key not currently present in the configuration
- **THEN** the key is added to the configuration with that value

### Requirement: Writing configuration preserves the rest of the file

Cobble SHALL change only the settings it was asked to change. Comments, blank lines, the order of settings, and settings that were not part of the request SHALL be preserved exactly.

#### Scenario: A hand-edited configuration is saved

- **WHEN** the configuration contains comments and operator-added settings and one setting is changed
- **THEN** the comments and operator-added settings are unchanged
- **AND** the order of settings is unchanged

#### Scenario: No effective change is submitted

- **WHEN** a write submits values identical to those already stored
- **THEN** the stored configuration is unchanged

#### Scenario: A write is interrupted

- **WHEN** a write does not complete
- **THEN** the stored configuration is either the previous content or the new content in full
- **AND** it is never left partially written

### Requirement: Submitted values are validated

Cobble SHALL validate submitted values against the type of each recognised setting and reject a write that would store a value of the wrong type. A value of the correct type that falls outside cobble's recorded range or recommendation SHALL be accepted and reported as a warning rather than rejected.

#### Scenario: A value of the wrong type is submitted

- **WHEN** a submitted value cannot be interpreted as the setting's type
- **THEN** the write is rejected
- **AND** the response identifies which setting was invalid and why
- **AND** no part of the configuration is changed

#### Scenario: A value outside the permitted set is submitted

- **WHEN** a submitted value for a setting with a fixed set of permitted values is not one of them
- **THEN** the write is rejected
- **AND** the response identifies which setting was invalid

#### Scenario: A value outside the recommended range is submitted

- **WHEN** a submitted value is of the correct type but outside cobble's recorded range
- **THEN** the value is persisted
- **AND** the response reports a warning identifying the setting and the expected range

#### Scenario: Several settings are invalid

- **WHEN** a write contains more than one invalid value
- **THEN** every invalid setting is identified in the response
- **AND** no part of the configuration is changed

### Requirement: The available worlds are reported

Because the level setting selects which of the server's worlds is loaded rather than naming the current one, cobble SHALL report the worlds present in the server's data, so that the setting can be presented as a choice among them.

#### Scenario: Worlds are requested

- **WHEN** the available worlds are requested
- **THEN** each world present in the server's data is reported
- **AND** the one the level setting currently names is identified

#### Scenario: The level setting names a world that is not present

- **WHEN** the level setting names a world that does not exist in the server's data
- **THEN** the current value is still reported
- **AND** it is identified as not present

#### Scenario: No worlds are present

- **WHEN** no world exists in the server's data
- **THEN** an empty set of worlds is reported
- **AND** no error is raised

#### Scenario: Selecting a world that does not exist creates one

- **WHEN** the level setting is changed to a name with no corresponding world
- **THEN** the write is accepted
- **AND** the response states that a new, empty world will be created when the server next starts

### Requirement: Configuration in effect is captured when the server starts

Cobble SHALL record the configuration values the managed server was started with, and SHALL retain that record for as long as that server process runs.

#### Scenario: The server is started

- **WHEN** the managed server is started
- **THEN** the configuration values it was started with are recorded

#### Scenario: The server is restarted

- **WHEN** the managed server is restarted
- **THEN** the recorded configuration is the configuration as it stood at the new start

#### Scenario: The server is not running

- **WHEN** the managed server is not running
- **THEN** no configuration is recorded as being in effect

### Requirement: Saved configuration that differs from the running server is reported

Because the Bedrock server reads its configuration only when it starts, cobble SHALL report which saved settings differ from those the running server was started with, so that an operator can see what a restart would apply.

#### Scenario: A setting is changed while the server runs

- **WHEN** a setting is changed and the managed server is running with a different value
- **THEN** that setting is reported as pending
- **AND** both the saved value and the value in effect are reported

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

### Requirement: Configuration writes are refused during maintenance

Because a maintenance operation may replace the server's data wholesale, cobble SHALL reject configuration writes while an update, backup, or restore is in progress.

#### Scenario: A write is attempted during maintenance

- **WHEN** a configuration write is requested while a maintenance operation is in progress
- **THEN** the write is rejected with an error identifying the maintenance operation
- **AND** the stored configuration is unchanged

#### Scenario: Configuration is read during maintenance

- **WHEN** the configuration is requested while a maintenance operation is in progress
- **THEN** the configuration is returned

#### Scenario: Maintenance completes

- **WHEN** a maintenance operation completes or is abandoned
- **THEN** configuration writes are accepted again
