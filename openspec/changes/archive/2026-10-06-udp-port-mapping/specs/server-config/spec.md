# Spec Delta

## MODIFIED Requirements

### Requirement: Player UDP port values are validated

Cobble SHALL reject a submitted `server-udp-ports` value that does not match the grammar the Bedrock server accepts. The value is empty, or one or more comma-separated entries. Each entry is a port, an inclusive `start-end` range, or a mapping `[address:]external:internal`. In a mapping, each side is a port or a range. The address is an IPv4 literal, a bracketed IPv6 literal, or a hostname. A hostname SHALL consist of dot-separated labels of letters, digits and hyphens, none starting or ending with a hyphen, each at most 63 characters, and at most 253 characters in total. An address made only of digits and dots SHALL be a valid IPv4 address. Cobble SHALL NOT look a hostname up. Every port SHALL be between 1 and 65535. A range's start SHALL NOT exceed its end. When both sides of a mapping are ranges they SHALL be the same length. The rejection SHALL name the setting and the reason, and nothing SHALL be written.

#### Scenario: A plain range is submitted

- **WHEN** `server-udp-ports` is submitted as `19140-19159`
- **THEN** it is accepted

#### Scenario: A mapping with an address is submitted

- **WHEN** `server-udp-ports` is submitted as `203.0.113.10:19132-19232:32000-32100`
- **THEN** it is accepted

#### Scenario: A mapping with a hostname is submitted

- **WHEN** `server-udp-ports` is submitted as `play.example.com:19140-19150:19140-19150`
- **THEN** it is accepted
- **AND** no name lookup is made

#### Scenario: A hostname that does not resolve is submitted

- **WHEN** `server-udp-ports` is submitted with a well-formed hostname that does not resolve
- **THEN** it is accepted

#### Scenario: An empty value is submitted

- **WHEN** `server-udp-ports` is submitted empty
- **THEN** it is accepted, and the server chooses player ports from the operating system's range

#### Scenario: A malformed value is submitted

- **WHEN** `server-udp-ports` is submitted as `19159-19140` or `abc` or `19132-19140:32000-32100`
- **THEN** the write is rejected with a reason naming `server-udp-ports`
- **AND** the stored configuration is unchanged

#### Scenario: A malformed address is submitted

- **WHEN** `server-udp-ports` is submitted as `1.2.3.999:19140:19140` or `-bad.example:19140:19140` or `my_host:19140:19140`
- **THEN** the write is rejected with a reason naming `server-udp-ports`
- **AND** the stored configuration is unchanged
