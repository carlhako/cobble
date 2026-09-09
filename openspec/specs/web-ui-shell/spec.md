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

### Requirement: A held backup can be downloaded from the interface

The web interface SHALL offer, for each backup in the backups list, a control that downloads that backup as a single file. The control SHALL be offered for every held backup, including one recorded as not restorable, so that a questionable backup can be taken elsewhere for inspection.

#### Scenario: Operator downloads a backup

- **WHEN** an operator activates the download control for a backup in the list
- **THEN** that backup is downloaded as a single file

#### Scenario: A not-restorable backup is listed

- **WHEN** the backups list contains a backup recorded as not restorable
- **THEN** a download control is still offered for it

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


### Requirement: The player roster is available from the interface

The interface SHALL present the players who have been observed on this server, showing for each their display name, total playtime, when they were last seen, and whether they are currently online. Players currently online SHALL be distinguishable from those who are not.

#### Scenario: The roster is viewed

- **WHEN** the operator opens the players section
- **THEN** every observed player is listed with display name, total playtime, and when they were last seen
- **AND** players currently online are distinguished from those who are not

#### Scenario: A player's sessions are inspected

- **WHEN** the operator selects a player
- **THEN** that player's individual sessions are shown, most recent first, each with its start time, duration, and how it ended

#### Scenario: A player connects or disconnects while the roster is open

- **WHEN** a player connects or disconnects
- **THEN** the roster reflects the change without operator action

#### Scenario: No players have been observed

- **WHEN** the players section is opened and no players have been observed
- **THEN** the interface explains that no player history has been recorded yet
- **AND** does not present it as an error

### Requirement: Approximate playtime is presented as approximate

Where a playtime or session end time was reconstructed rather than observed, the interface SHALL present it as approximate rather than exact, so that an operator is never shown a reconstructed figure indistinguishable from a measured one.

#### Scenario: A session's end time was reconstructed

- **WHEN** a session whose end time was reconstructed is displayed
- **THEN** it is marked as approximate
- **AND** the reason its end time was reconstructed is available

#### Scenario: A total includes reconstructed sessions

- **WHEN** a player's total playtime includes one or more reconstructed sessions
- **THEN** the total is presented as approximate

### Requirement: The recorded period is visible in the roster

The interface SHALL make visible the date from which player history has been recorded, so that an operator whose server predates player history does not read its absence as data loss.

#### Scenario: The roster is viewed on an installation that predates recording

- **WHEN** the players section is opened
- **THEN** the date from which player history has been recorded is shown

### Requirement: Gamerules are editable from the interface

The interface SHALL present the active world's gamerules with their current values, typed according to each rule — a checkbox for a boolean, a bounded number for an integer, a choice for an enumerated rule — and SHALL apply a change without requiring the operator to restart the server. A rule cobble has no type information for SHALL be presented as editable text and SHALL NOT be hidden.

#### Scenario: The gamerules are viewed

- **WHEN** the operator opens the gamerules section and the server is running
- **THEN** every gamerule reported by the server is listed with its current value, presented according to its type

#### Scenario: A rule is changed

- **WHEN** the operator changes a gamerule and the server is running
- **THEN** the change is applied to the running server
- **AND** the value shown afterwards is the value read back from the server
- **AND** no restart is offered or required

#### Scenario: A change is rejected

- **WHEN** a submitted gamerule value is refused
- **THEN** the reason is shown against that rule
- **AND** the displayed value returns to the value in effect

#### Scenario: A rule of unknown type

- **WHEN** the server reports a gamerule the interface has no type information for
- **THEN** it is shown as editable text and marked as unrecognised

### Requirement: The gamerule presentation distinguishes live values from recorded ones

Because gamerules can only be read from a running server, the interface SHALL make clear whether the values shown are live or were recorded earlier, and SHALL never present a recorded value as current.

#### Scenario: The server is stopped

- **WHEN** the operator opens the gamerules section and the server is not running
- **THEN** the last recorded values for the active world are shown, marked as recorded, with the time they were taken

#### Scenario: A world that has never been read

- **WHEN** the active world has no recorded gamerules and the server is not running
- **THEN** the section states that the rules have not been read rather than showing any values

#### Scenario: A change made while stopped

- **WHEN** the operator changes a gamerule while the server is not running
- **THEN** the interface states that the change will be applied when the server next starts

### Requirement: Gamerule changes made outside the interface are surfaced

The interface SHALL show the operator when cobble has adopted a gamerule changed in game, re-applied recorded rules after a restore, or applied preferred defaults to a new world, and SHALL allow the operator to acknowledge it.

#### Scenario: A rule was changed in game

- **WHEN** cobble has adopted a gamerule changed outside the interface
- **THEN** the interface reports which rule changed and the value cobble has saved

#### Scenario: Rules were repaired after a restore

- **WHEN** cobble has re-applied recorded gamerules following a restore
- **THEN** the interface reports which rules were re-applied and why

#### Scenario: The report is acknowledged

- **WHEN** the operator acknowledges the report
- **THEN** it is dismissed and does not reappear
- **AND** the gamerule values are unchanged

### Requirement: Preferred gamerule defaults are editable from the interface

The interface SHALL let the operator maintain a set of preferred gamerule values to be applied to any world cobble observes for the first time, and SHALL make clear that they do not affect worlds already recorded.

#### Scenario: Defaults are edited

- **WHEN** the operator sets a preferred default for a gamerule
- **THEN** it is saved
- **AND** the interface states that it applies only to worlds cobble has not seen before

#### Scenario: Defaults are distinguished from the active world's values

- **WHEN** the operator views the preferred defaults
- **THEN** they are presented separately from the active world's current gamerules

### Requirement: Gamerule editing is unavailable during maintenance

The interface SHALL prevent gamerule changes while an update, backup, or restore is in progress, and SHALL continue to present the current values.

#### Scenario: Maintenance begins while the section is open

- **WHEN** a maintenance operation starts while the operator has the gamerules section open
- **THEN** editing becomes unavailable with the operation in progress named
- **AND** the values remain visible

#### Scenario: Maintenance completes

- **WHEN** the maintenance operation finishes
- **THEN** editing becomes available again without the operator reloading the interface

### Requirement: Long setting lists can be filtered by name

The web interface SHALL provide, at the top of the Configuration section and the Gamerules section, a filter field that narrows the list of settings or rules shown below it as the operator types. A setting or rule SHALL be shown when the entered text matches its name or its description. Clearing the field SHALL restore the full list. The filter SHALL operate within the interface without reloading the section or contacting the server.

The filter SHALL apply only to the list of settings or rules. Status, maintenance, pending-change, and report information SHALL remain visible regardless of the filter. On the Gamerules section the filter SHALL narrow the active world's rule list; the preferred-defaults editor is not affected.

#### Scenario: Operator types in the filter field

- **WHEN** an operator enters text in the filter field of the Configuration or Gamerules section
- **THEN** only settings or rules whose name or description matches the entered text remain shown
- **AND** the list updates as the operator types, without a reload

#### Scenario: Operator clears the filter field

- **WHEN** an operator clears the filter field
- **THEN** every setting or rule in the section is shown again

#### Scenario: No setting matches the entered text

- **WHEN** the entered text matches no setting or rule
- **THEN** the interface states that nothing matches
- **AND** the entered text is retained so the operator can adjust it

#### Scenario: Pending and status information while a filter is applied

- **WHEN** a filter is applied and the section has pending changes, a maintenance operation, or a report to show
- **THEN** that information remains visible
- **AND** only the list of settings or rules is narrowed

### Requirement: Moderation actions are available from the player roster

The interface SHALL offer kick, ban, unban, and operator-rights actions on a player's entry in the roster, so that acting on a player happens where that player is already shown.

#### Scenario: A player is selected

- **WHEN** a player's roster entry is opened
- **THEN** the actions available for that player are presented
- **AND** each player's current access state is shown with their history

#### Scenario: A player is not currently online

- **WHEN** an offline player's entry is opened
- **THEN** kick is presented as unavailable
- **AND** ban, unban, and operator-rights actions remain available

#### Scenario: The server is not running

- **WHEN** the roster is opened while the managed server is not running
- **THEN** kick is presented as unavailable
- **AND** the durable actions remain available

#### Scenario: An action is applied

- **WHEN** a moderation action completes
- **THEN** the player's entry reflects the new state without the operator reloading

#### Scenario: An action is refused

- **WHEN** a moderation action is refused
- **THEN** the reason is presented with the player it concerns
- **AND** the presented state continues to reflect what the server reports

### Requirement: Banning names who else it would exclude

Because enabling the allowlist excludes every player not on it, the interface SHALL present who would be excluded before a ban that enables enforcement is applied.

#### Scenario: A ban would enable enforcement

- **WHEN** a ban is requested while allowlist enforcement is off
- **THEN** the interface presents that enforcement will be enabled
- **AND** it names the players who have played on this server and are not on the allowlist
- **AND** the ban is not applied until it is confirmed

#### Scenario: The excluded players are carried onto the list

- **WHEN** the operator chooses to permit the players the change would exclude
- **THEN** those players are added to the allowlist as part of the same action

#### Scenario: Enforcement is already on

- **WHEN** a ban is requested while enforcement is already in effect
- **THEN** no exclusion warning is presented

#### Scenario: A ban is confirmed

- **WHEN** a ban is confirmed
- **THEN** the parts of it that were carried out are presented afterwards

### Requirement: A ban is presented with its reason and time

The interface SHALL present a banned player's reason and ban time, and distinguish a banned player from one who is merely absent from the allowlist.

#### Scenario: A banned player is shown

- **WHEN** a banned player is presented
- **THEN** the reason and the time of the ban are shown

#### Scenario: A player was never banned

- **WHEN** a player absent from the allowlist has no ban record
- **THEN** they are not presented as banned

### Requirement: The allowlist and permissions are visible from the interface

The interface SHALL present the allowlist and the permission records, including entries with no counterpart in the roster, so that the presented list is never a partial view of itself.

#### Scenario: The allowlist is shown

- **WHEN** the allowlist is presented
- **THEN** every entry is shown
- **AND** entries naming players who have never played here are shown as such

#### Scenario: An entry has no stable identifier

- **WHEN** an allowlist entry has no stable identifier
- **THEN** it is presented as identified by name alone

#### Scenario: A permission record names an unknown identifier

- **WHEN** a permission record names an identifier absent from the roster
- **THEN** the record is presented with its identifier and no name

### Requirement: Allowlist enforcement state is presented distinctly from the saved setting

The interface SHALL present whether the allowlist is being enforced right now separately from what the saved configuration says, so that a divergence between them is visible rather than silent.

#### Scenario: The two agree

- **WHEN** the enforcement in effect matches the saved setting
- **THEN** the enforcement state is presented as a single settled value

#### Scenario: The two disagree

- **WHEN** the enforcement in effect differs from the saved setting
- **THEN** both are presented
- **AND** which one is in effect now is identified

#### Scenario: The state has not been observed

- **WHEN** cobble has not observed the running server's enforcement state
- **THEN** it is presented as unknown rather than as a value

### Requirement: Moderation is unavailable during maintenance

The interface SHALL present moderation actions as unavailable while an update, backup, or restore is in progress, so that a refusal is anticipated rather than encountered.

#### Scenario: Maintenance begins

- **WHEN** an update, backup, or restore begins
- **THEN** the moderation actions are presented as unavailable
- **AND** the reason is presented

#### Scenario: Maintenance completes

- **WHEN** maintenance completes
- **THEN** the actions become available again without the operator reloading

#### Scenario: Reading remains available

- **WHEN** maintenance is in progress
- **THEN** the roster, allowlist, permissions, and ban records remain readable
