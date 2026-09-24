# Spec Delta

## Purpose

Describes how players reach the Bedrock server: the network settings that apply to the configured transport, the player UDP port range, the ports an operator must forward for external players, and whether the pinned port range can hold the configured player count.

## ADDED Requirements

### Requirement: The network settings for the saved transport are reported

Cobble SHALL report the network settings that apply to the saved transport, which is the transport the server uses at its next start. For each setting it SHALL report the key, the current value (or the default when the setting is absent from the configuration), and the protocol the setting governs under that transport. Under NetherNet these SHALL be the handshake port (`server-port`, TCP), the bind address (`server-ip`) and the player UDP port range (`server-udp-ports`). Under RakNet they SHALL be the IPv4 port (`server-port`, UDP) and the IPv6 port (`server-portv6`, UDP). The saved transport and the transport the running server started with SHALL both be reported.

#### Scenario: The saved transport is NetherNet

- **WHEN** the network settings are requested and the saved transport is `nethernet`
- **THEN** the handshake port is reported as TCP
- **AND** the bind address and the player UDP port range are reported
- **AND** the IPv6 port is not reported

#### Scenario: The saved transport is RakNet

- **WHEN** the network settings are requested and the saved transport is `raknet`
- **THEN** the IPv4 and IPv6 ports are reported as UDP
- **AND** the bind address and the player UDP port range are not reported

#### Scenario: The transport is absent from the configuration

- **WHEN** the configuration does not set a transport
- **THEN** the active version's default transport is treated as the saved transport

#### Scenario: A transport switch is saved while the server runs

- **WHEN** the saved transport differs from the one the running server started with
- **THEN** the settings reported are those of the saved transport
- **AND** the running transport is reported alongside it

#### Scenario: LAN discovery under NetherNet

- **WHEN** the saved transport is `nethernet`
- **THEN** LAN discovery is reported as UDP 7551, for information only

### Requirement: The player UDP port range is reported in structured form

Cobble SHALL report the player UDP port range in one of three forms: chosen by the operating system (the setting is empty or absent), a single local port range (a single port or an inclusive `start-end` range, with no mapping or address), or custom (any other valid value, including a NAT mapping, an address prefix, or several entries). A custom value SHALL be reported verbatim with the local ports it confines the server to.

#### Scenario: No range is pinned

- **WHEN** `server-udp-ports` is empty or absent
- **THEN** the range is reported as chosen by the operating system

#### Scenario: A plain range is pinned

- **WHEN** `server-udp-ports` is `19140-19159`
- **THEN** the range is reported with start 19140 and end 19159
- **AND** a size of 20 ports

#### Scenario: A single port is pinned

- **WHEN** `server-udp-ports` is `19140`
- **THEN** the range is reported with start and end 19140 and a size of 1

#### Scenario: A mapping is configured

- **WHEN** `server-udp-ports` is `203.0.113.10:19132-19232:32000-32100`
- **THEN** the range is reported as custom with that value verbatim
- **AND** the local ports it confines the server to are 32000-32100

### Requirement: The ports to forward for external players are reported

Cobble SHALL report, for the saved transport, the protocol and port or port range an operator must forward to the server for players outside the local network. Under NetherNet these SHALL be TCP on the handshake port and UDP on the pinned local range. When no range is pinned, cobble SHALL report instead that forwarding is not possible until a range is pinned. Under RakNet they SHALL be UDP on the IPv4 port and UDP on the IPv6 port, with the IPv6 port marked as needed only for IPv6 players. LAN discovery SHALL NOT be listed as a port to forward.

#### Scenario: NetherNet with a pinned range

- **WHEN** the transport is `nethernet`, `server-port` is 19132 and `server-udp-ports` is `19140-19159`
- **THEN** the ports to forward are TCP 19132 and UDP 19140-19159

#### Scenario: NetherNet with no pinned range

- **WHEN** the transport is `nethernet` and no range is pinned
- **THEN** TCP on the handshake port is reported
- **AND** the report states that player UDP traffic cannot be forwarded until a range is pinned

#### Scenario: NetherNet with a custom value

- **WHEN** `server-udp-ports` holds a mapping
- **THEN** the external ports of the mapping are reported as the UDP ports to forward

#### Scenario: RakNet

- **WHEN** the transport is `raknet`, `server-port` is 19132 and `server-portv6` is 19133
- **THEN** the ports to forward are UDP 19132, and UDP 19133 marked as needed only for IPv6 players

### Requirement: The player UDP port range is checked against the player limit

Because each connected NetherNet player uses its own UDP port, cobble SHALL report a mismatch when the saved transport is `nethernet`, a player UDP port range is pinned, and the number of local ports it confines the server to is less than `max-players`. The mismatch SHALL name both values. No mismatch SHALL be reported under RakNet or when no range is pinned.

#### Scenario: The range is smaller than the player limit

- **WHEN** the transport is `nethernet`, `server-udp-ports` is `19140-19144` and `max-players` is 10
- **THEN** a mismatch is reported naming 5 ports and 10 players

#### Scenario: The range covers the player limit

- **WHEN** `server-udp-ports` is `19140-19159` and `max-players` is 10
- **THEN** no mismatch is reported

#### Scenario: No range is pinned

- **WHEN** the transport is `nethernet` and no range is pinned
- **THEN** no mismatch is reported

#### Scenario: RakNet

- **WHEN** the transport is `raknet` and a small range is still in the configuration
- **THEN** no mismatch is reported
