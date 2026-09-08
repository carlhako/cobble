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

### Requirement: Version and update state are presented in the interface

The web interface SHALL present the installed Bedrock version, whether a newer version is available, when updates were last checked and applied, and when the next scheduled check will occur.

#### Scenario: A newer version is available

- **WHEN** a newer Bedrock version is available
- **THEN** the interface shows the installed version and the available version
- **AND** it indicates that an update is pending

#### Scenario: The server is current

- **WHEN** no newer version is available
- **THEN** the interface reports the installation as up to date

#### Scenario: Operator requests an update check

- **WHEN** an operator requests an update check from the interface
- **THEN** the check is performed
- **AND** the result is reflected without the operator refreshing

### Requirement: A failed update is surfaced with its diagnostics

The web interface SHALL alert the operator when an update has failed, and SHALL present the version attempted, the step at which it failed, and the server output captured during the attempt, without requiring access to the host's system logs.

#### Scenario: An update has failed

- **WHEN** the most recent update failed and was rolled back
- **THEN** the interface presents an alert stating that the update failed and was rolled back
- **AND** the version attempted, the failing step, and the captured output are available from that alert

#### Scenario: A version is not being retried

- **WHEN** the available version is one that previously failed an update
- **THEN** the interface indicates that it will not be retried automatically
- **AND** an operator can clear that record from the interface

#### Scenario: Rollback could not restore service

- **WHEN** a rollback failed to restore a running server
- **THEN** the interface presents this as requiring operator intervention

### Requirement: Backup and restore are available from the interface

The web interface SHALL list the backups cobble holds, allow an operator to capture a backup, and allow an operator to restore one.

#### Scenario: Backups are listed

- **WHEN** an operator views the backups section
- **THEN** each backup is listed with its capture time, recorded server version, and size

#### Scenario: Operator captures a backup

- **WHEN** an operator requests a backup from the interface
- **THEN** the backup is captured
- **AND** progress and the outcome are reflected without the operator refreshing

#### Scenario: Operator restores a backup

- **WHEN** an operator selects a backup to restore
- **THEN** the interface requires an explicit confirmation that identifies the backup and states that current state will be replaced
- **AND** the restore is performed only after that confirmation

#### Scenario: Backups are failing

- **WHEN** backups are failing because the destination cannot be written
- **THEN** the interface presents this as an unhealthy condition with the reason

### Requirement: Maintenance progress is reflected without operator action

The web interface SHALL indicate when an update, backup, or restore is in progress, show which step it has reached, and reflect its completion without the operator refreshing or re-navigating.

#### Scenario: A maintenance operation is in progress

- **WHEN** an update, backup, or restore is in progress
- **THEN** the interface indicates the operation and the step it has reached
- **AND** lifecycle actions that conflict with it are not offered

#### Scenario: A maintenance operation completes

- **WHEN** the operation completes
- **THEN** the interface reflects the new state without operator action

#### Scenario: The interface is opened during a maintenance operation

- **WHEN** an operator opens the interface while a maintenance operation is already in progress
- **THEN** the operation and its current step are shown

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
