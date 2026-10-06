# Spec Delta

## MODIFIED Requirements

### Requirement: Network settings are editable from the interface

The interface SHALL provide a network section, listed in navigation. It SHALL present the network settings for the saved transport, labelled with the protocol each governs, and the ports to forward for external players (see `server-network`). The operator SHALL be able to switch the transport there. Saving goes through the same configuration write as the configuration section, with the same validation, maintenance, and pending-restart behaviour. The bind address SHALL be labelled as this machine's address, to tell it apart from the address players reach.

The player UDP ports SHALL be edited either as chosen by the operating system, or as one entry. An entry has an optional address players reach (an IP address or a hostname), a local start and end port, and an external start and end port. Blank external ports SHALL mean the same ports as local. A blank end port SHALL mean a single port. The section SHALL save the shortest value that has the same meaning: a plain port or range when there is no address and the external ports equal the local ones, and a mapping otherwise. An IPv6 address entered without brackets SHALL be saved in brackets. When the address is a hostname, the section SHALL note that the server may need a restart to pick up a change in the hostname's IP address. The section SHALL NOT detect a public address or look a hostname up.

#### Scenario: The section is opened under NetherNet

- **WHEN** an operator opens the network section and the saved transport is `nethernet`
- **THEN** the handshake port is shown as TCP, with the bind address and the player UDP ports
- **AND** LAN discovery on UDP 7551 is shown for information
- **AND** the ports to forward are listed

#### Scenario: The section is opened under RakNet

- **WHEN** the saved transport is `raknet`
- **THEN** the IPv4 and IPv6 ports are shown as UDP
- **AND** the bind address and the player UDP ports are not shown
- **AND** the ports to forward are listed

#### Scenario: The operator switches the transport

- **WHEN** the operator selects the other transport
- **THEN** the section shows that transport's settings
- **AND** settings belonging only to the other transport are left unchanged in the configuration when saved

#### Scenario: The operator pins a range

- **WHEN** the operator enters a local start and end port, leaves the address and external ports blank, and saves
- **THEN** `server-udp-ports` is saved as that range
- **AND** the ports to forward include it

#### Scenario: The operator maps external ports to local ports

- **WHEN** the operator enters local ports 19140-19150 and external ports 19132-19142 with no address, and saves
- **THEN** `server-udp-ports` is saved as `19132-19142:19140-19150`
- **AND** the ports to forward show UDP 19132-19142 translating to 19140-19150

#### Scenario: The operator enters the address players reach

- **WHEN** the operator enters `play.example.com` as the address and local ports 19140-19150, leaves the external ports blank, and saves
- **THEN** `server-udp-ports` is saved as `play.example.com:19140-19150:19140-19150`
- **AND** the section notes that the server may need a restart if the hostname's IP address changes

#### Scenario: The operator enters an IP address

- **WHEN** the operator enters `203.0.113.10` as the address
- **THEN** the hostname restart note is not shown

#### Scenario: The operator enters a bare IPv6 address

- **WHEN** the operator enters `2001:db8::1` as the address, with local ports 19140-19150, and saves
- **THEN** `server-udp-ports` is saved as `[2001:db8::1]:19140-19150:19140-19150`

#### Scenario: External and local ranges differ in size

- **WHEN** the operator enters a local range and an external range of different sizes
- **THEN** the section shows that the ranges must be the same size, beside the player UDP ports
- **AND** saving is not offered until it is corrected

#### Scenario: A saved mapping is opened

- **WHEN** `server-udp-ports` holds a single mapping
- **THEN** the address, local ports and external ports are shown in their fields for editing

#### Scenario: The operator lets the operating system choose

- **WHEN** the operator chooses to let the operating system pick player ports and saves
- **THEN** `server-udp-ports` is saved empty
- **AND** the section states that external players cannot connect until a range is pinned

#### Scenario: The range holds a value the form cannot represent

- **WHEN** `server-udp-ports` holds a custom value, such as several entries or a value that does not parse
- **THEN** the value is shown read-only, with a pointer to the configuration section for editing
- **AND** saving the section does not change it

#### Scenario: A change is saved while the server runs

- **WHEN** a network setting or the transport is saved while the server is running
- **THEN** the section shows that a restart is needed for it to take effect, as for any pending configuration change

#### Scenario: Maintenance is in progress

- **WHEN** a maintenance operation is in progress
- **THEN** the network settings are shown and saving is not offered
