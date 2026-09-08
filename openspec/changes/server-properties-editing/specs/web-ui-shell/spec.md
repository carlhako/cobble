## ADDED Requirements

### Requirement: Server configuration is editable from the interface

The web interface SHALL present the server's configuration settings and allow an operator to change them. Settings cobble recognises SHALL be presented with an input appropriate to their type and with their documented default and meaning; settings cobble does not recognise SHALL be presented as editable text.

#### Scenario: Operator views the configuration section

- **WHEN** an operator opens the configuration section
- **THEN** every setting present in the server's configuration is shown with its current value

#### Scenario: A recognised setting is shown

- **WHEN** a shown setting is one cobble recognises
- **THEN** its input reflects its type
- **AND** its documented default and meaning are available to the operator

#### Scenario: An unrecognised setting is shown

- **WHEN** a shown setting is one cobble does not recognise
- **THEN** it is presented as an editable text value
- **AND** it is identified as not recognised by cobble

#### Scenario: Operator saves a change

- **WHEN** an operator changes settings and saves
- **THEN** the changes are persisted
- **AND** the outcome is reflected without the operator refreshing

#### Scenario: A submitted value is invalid

- **WHEN** a save is rejected because a value is invalid
- **THEN** the interface identifies each invalid setting and the reason
- **AND** the operator's entered values are retained for correction

#### Scenario: A submitted value is outside the recommended range

- **WHEN** a saved value is accepted with a warning
- **THEN** the interface presents the warning alongside that setting

### Requirement: The interface presents the level setting as a choice of world

Because the level setting selects which world the server loads rather than naming the current one, the web interface SHALL present it as a choice among the worlds that exist, and SHALL make creating a new world a separate, explicitly labelled action.

#### Scenario: Operator views the level setting

- **WHEN** an operator views the level setting
- **THEN** the worlds present in the server's data are offered as choices
- **AND** the currently selected world is indicated

#### Scenario: Operator chooses to create a new world

- **WHEN** an operator chooses to create a new world and names it
- **THEN** the interface states that a new, empty world will be created and that the existing worlds are kept
- **AND** the change is saved only after the operator confirms

#### Scenario: The selected world is not present

- **WHEN** the level setting names a world that does not exist in the server's data
- **THEN** the interface shows the current value
- **AND** indicates that no world of that name exists

### Requirement: Pending configuration changes and the restart to apply them are surfaced

Because saved configuration does not affect a running server, the web interface SHALL indicate when saved settings differ from those in effect, offer a restart to apply them, and allow the operator to defer that restart.

#### Scenario: Configuration is saved while the server is running

- **WHEN** an operator saves configuration and the server is running
- **THEN** the interface reports that the changes are saved but not yet in effect
- **AND** offers to restart the server

#### Scenario: Operator applies the changes

- **WHEN** an operator accepts the offered restart
- **THEN** the server is restarted
- **AND** the interface reflects that no changes remain pending

#### Scenario: Operator defers the restart

- **WHEN** an operator declines the offered restart
- **THEN** the changes remain saved
- **AND** the interface continues to show that changes are pending
- **AND** it states that they will take effect the next time the server starts for any reason

#### Scenario: The interface is opened with changes already pending

- **WHEN** an operator opens the interface while configuration changes are pending
- **THEN** the pending state is shown without the operator having made the change in that session
- **AND** which settings differ, and their saved and in-effect values, are available

#### Scenario: Configuration is saved while the server is stopped

- **WHEN** an operator saves configuration and the server is not running
- **THEN** no restart is offered
- **AND** no changes are reported as pending

### Requirement: Configuration editing is unavailable during maintenance

The web interface SHALL not offer configuration saving while an update, backup, or restore is in progress, and SHALL explain why.

#### Scenario: Maintenance is in progress

- **WHEN** an operator opens the configuration section while a maintenance operation is in progress
- **THEN** the settings are shown
- **AND** saving is not offered
- **AND** the interface states which maintenance operation is in progress

#### Scenario: Maintenance completes while the section is open

- **WHEN** the maintenance operation completes
- **THEN** saving becomes available without the operator refreshing
