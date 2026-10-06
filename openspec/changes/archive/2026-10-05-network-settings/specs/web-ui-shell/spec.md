# Spec Delta

## MODIFIED Requirements

### Requirement: Server configuration is editable from the interface

The web interface SHALL present the server's configuration settings and allow an operator to change them. Settings cobble recognises SHALL be presented with an input appropriate to their type and with their documented default and meaning. Settings cobble does not recognise SHALL be presented as editable text. Recognised settings absent from the configuration SHALL be presented as not set, and an operator SHALL be able to set them.

#### Scenario: Operator views the configuration section

- **WHEN** an operator opens the configuration section
- **THEN** every setting present in the server's configuration is shown with its current value
- **AND** every recognised setting absent from the configuration is shown as not set

#### Scenario: A recognised setting is shown

- **WHEN** a shown setting is one cobble recognises
- **THEN** its input reflects its type
- **AND** its documented default and meaning are available to the operator

#### Scenario: An unrecognised setting is shown

- **WHEN** a shown setting is one cobble does not recognise
- **THEN** it is presented as an editable text value
- **AND** it is identified as not recognised by cobble

#### Scenario: A recognised setting that is not set is shown

- **WHEN** a shown setting is recognised but absent from the configuration
- **THEN** it is identified as not set, with its default
- **AND** entering a value and saving adds it to the configuration

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

## ADDED Requirements

### Requirement: Network settings are editable from the interface

The interface SHALL provide a network section, listed in navigation. It SHALL present the network settings for the saved transport, labelled with the protocol each governs, and the ports to forward for external players (see `server-network`). The operator SHALL be able to switch the transport there. Saving goes through the same configuration write as the configuration section, with the same validation, maintenance, and pending-restart behaviour. The player UDP port range SHALL be edited as a start and end port, or as chosen by the operating system. The section SHALL NOT show, request, or detect a public address.

#### Scenario: The section is opened under NetherNet

- **WHEN** an operator opens the network section and the saved transport is `nethernet`
- **THEN** the handshake port is shown as TCP, with the bind address and the player UDP port range
- **AND** LAN discovery on UDP 7551 is shown for information
- **AND** the ports to forward are listed

#### Scenario: The section is opened under RakNet

- **WHEN** the saved transport is `raknet`
- **THEN** the IPv4 and IPv6 ports are shown as UDP
- **AND** the bind address and the player UDP port range are not shown
- **AND** the ports to forward are listed

#### Scenario: The operator switches the transport

- **WHEN** the operator selects the other transport
- **THEN** the section shows that transport's settings
- **AND** settings belonging only to the other transport are left unchanged in the configuration when saved

#### Scenario: The operator pins a range

- **WHEN** the operator enters a start and end port and saves
- **THEN** `server-udp-ports` is saved as that range
- **AND** the ports to forward include it

#### Scenario: The operator lets the operating system choose

- **WHEN** the operator chooses to let the operating system pick player ports and saves
- **THEN** `server-udp-ports` is saved empty
- **AND** the section states that external players cannot connect until a range is pinned

#### Scenario: The range holds a value the form cannot represent

- **WHEN** `server-udp-ports` holds a custom value such as a mapping or several entries
- **THEN** the value is shown read-only, with a pointer to the configuration section for editing
- **AND** saving the section does not change it

#### Scenario: A change is saved while the server runs

- **WHEN** a network setting or the transport is saved while the server is running
- **THEN** the section shows that a restart is needed for it to take effect, as for any pending configuration change

#### Scenario: Maintenance is in progress

- **WHEN** a maintenance operation is in progress
- **THEN** the network settings are shown and saving is not offered

### Requirement: Configuration conflicts are shown at the top of the configuration and network sections

While the saved configuration contains a conflict (see `server-config`), the interface SHALL show it in a banner at the top of both the configuration section and the network section. The banner SHALL name the settings involved and what to change. It SHALL appear after a save on either section introduces the conflict, and SHALL disappear once a save resolves it, without the operator refreshing.

#### Scenario: The player limit is raised past the range

- **WHEN** an operator raises `max-players` above the pinned UDP range's size in the configuration section and saves
- **THEN** a banner at the top of the configuration section reports the mismatch
- **AND** the network section shows the same banner when opened

#### Scenario: The range is narrowed below the player limit

- **WHEN** an operator narrows the player UDP range below `max-players` in the network section and saves
- **THEN** a banner at the top of the network section reports the mismatch
- **AND** the configuration section shows the same banner when opened

#### Scenario: The conflict is resolved

- **WHEN** a save removes the conflict
- **THEN** the banner disappears from both sections

#### Scenario: The conflict was introduced outside cobble

- **WHEN** the configuration file is edited by hand into a conflict
- **THEN** the banner is shown the next time either section is opened
