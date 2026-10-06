# Spec Delta

## MODIFIED Requirements

### Requirement: The player UDP port range is reported in structured form

Cobble SHALL report the player UDP port range in one of three forms. The first is chosen by the operating system: the setting is empty or absent. The second is a single entry: exactly one port, range or mapping. It SHALL be reported as its local ports (start, end and size), its external ports (start and end) when it is a mapping, and its address when one is given. The third is custom: any other value, including several entries or a value that does not parse. A custom value SHALL be reported verbatim, with the local ports it confines the server to.

#### Scenario: No range is pinned

- **WHEN** `server-udp-ports` is empty or absent
- **THEN** the range is reported as chosen by the operating system

#### Scenario: A plain range is pinned

- **WHEN** `server-udp-ports` is `19140-19159`
- **THEN** the range is reported with local start 19140 and end 19159
- **AND** a size of 20 ports
- **AND** no external ports and no address

#### Scenario: A single port is pinned

- **WHEN** `server-udp-ports` is `19140`
- **THEN** the range is reported with local start and end 19140 and a size of 1

#### Scenario: A mapping is configured

- **WHEN** `server-udp-ports` is `203.0.113.10:19132-19232:32000-32100`
- **THEN** the range is reported as a single entry with local start 32000 and end 32100
- **AND** external start 19132 and end 19232
- **AND** address `203.0.113.10`

#### Scenario: A mapping with a hostname is configured

- **WHEN** `server-udp-ports` is `play.example.com:19140-19150:19140-19150`
- **THEN** the range is reported as a single entry with local and external ports 19140-19150
- **AND** address `play.example.com`

#### Scenario: Several entries are configured

- **WHEN** `server-udp-ports` is `19140-19149,19160-19169`
- **THEN** the range is reported as custom with that value verbatim
- **AND** the local ports it confines the server to are 19140-19149 and 19160-19169

### Requirement: The ports to forward for external players are reported

Cobble SHALL report, for the saved transport, the protocol and port or port range an operator must forward to the server for players outside the local network. Under NetherNet these SHALL be TCP on the handshake port and UDP on the player ports. For each player port entry, the UDP ports to forward SHALL be the external ports, and when they differ from the local ports, the local ports they translate to SHALL be reported with them. When no range is pinned, cobble SHALL report instead that forwarding is not possible until a range is pinned. Under RakNet they SHALL be UDP on the IPv4 port and UDP on the IPv6 port, with the IPv6 port marked as needed only for IPv6 players. LAN discovery SHALL NOT be listed as a port to forward.

#### Scenario: NetherNet with a pinned range

- **WHEN** the transport is `nethernet`, `server-port` is 19132 and `server-udp-ports` is `19140-19159`
- **THEN** the ports to forward are TCP 19132 and UDP 19140-19159
- **AND** no translation is reported

#### Scenario: NetherNet with no pinned range

- **WHEN** the transport is `nethernet` and no range is pinned
- **THEN** TCP on the handshake port is reported
- **AND** the report states that player UDP traffic cannot be forwarded until a range is pinned

#### Scenario: NetherNet with a mapping

- **WHEN** `server-udp-ports` is `19132-19142:19140-19150`
- **THEN** UDP 19132-19142 is reported as a port range to forward
- **AND** it is reported as translating to local ports 19140-19150

#### Scenario: NetherNet with a mapping whose sides are equal

- **WHEN** `server-udp-ports` is `play.example.com:19140-19150:19140-19150`
- **THEN** UDP 19140-19150 is reported as a port range to forward
- **AND** no translation is reported

#### Scenario: NetherNet with a custom value

- **WHEN** `server-udp-ports` holds several entries, such as `19132:19140,19133:19141`
- **THEN** one UDP line is reported per entry, each with its external port and the local port it translates to

#### Scenario: NetherNet with a value that does not parse

- **WHEN** `server-udp-ports` holds a value that does not parse
- **THEN** TCP on the handshake port is reported
- **AND** no UDP ports are reported

#### Scenario: RakNet

- **WHEN** the transport is `raknet`, `server-port` is 19132 and `server-portv6` is 19133
- **THEN** the ports to forward are UDP 19132, and UDP 19133 marked as needed only for IPv6 players
