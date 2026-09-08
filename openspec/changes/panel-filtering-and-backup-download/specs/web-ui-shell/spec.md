## ADDED Requirements

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

### Requirement: A held backup can be downloaded from the interface

The web interface SHALL offer, for each backup in the backups list, a control that downloads that backup as a single file. The control SHALL be offered for every held backup, including one recorded as not restorable, so that a questionable backup can be taken elsewhere for inspection.

#### Scenario: Operator downloads a backup

- **WHEN** an operator activates the download control for a backup in the list
- **THEN** that backup is downloaded as a single file

#### Scenario: A not-restorable backup is listed

- **WHEN** the backups list contains a backup recorded as not restorable
- **THEN** a download control is still offered for it
