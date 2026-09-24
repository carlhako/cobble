# Spec Delta

## MODIFIED Requirements

### Requirement: Server configuration is readable

Cobble SHALL expose the current contents of the Bedrock server's configuration as a set of settings, each with its key and current value. Settings that cobble recognises SHALL additionally carry their type, documented default, and permitted values or range. Settings present in the configuration that cobble does not recognise SHALL still be exposed with their key and value. Settings that cobble recognises but that are absent from the configuration SHALL also be exposed, identified as not set, with their documented default as their value.

#### Scenario: Configuration is requested

- **WHEN** the server configuration is requested
- **THEN** every setting present in the configuration is returned with its current value
- **AND** every recognised setting absent from the configuration is returned as not set

#### Scenario: A recognised setting is returned

- **WHEN** a returned setting is one cobble recognises
- **THEN** its type, documented default, and permitted values or range are included

#### Scenario: An unrecognised setting is present

- **WHEN** the configuration contains a setting cobble does not recognise
- **THEN** that setting is returned with its key and value
- **AND** it is identified as unrecognised
- **AND** no error is raised

#### Scenario: A recognised setting is absent

- **WHEN** a setting cobble recognises is not assigned anywhere in the configuration, for example `server-udp-ports`, which the vendor file does not ship
- **THEN** it is returned identified as not set
- **AND** its value is its documented default
- **AND** reading does not add it to the configuration

#### Scenario: An absent setting is then set

- **WHEN** a value is submitted for a recognised setting that is not set
- **THEN** the key is added to the configuration with that value
- **AND** a subsequent read no longer identifies it as not set

#### Scenario: Configuration is requested while the server is stopped

- **WHEN** the configuration is requested and the managed server is not running
- **THEN** the configuration is returned

#### Scenario: A setting appears more than once

- **WHEN** the same key is assigned more than once in the configuration
- **THEN** the value reported is the one the Bedrock server would use

## ADDED Requirements

### Requirement: Player UDP port values are validated

Cobble SHALL reject a submitted `server-udp-ports` value that does not match the grammar the Bedrock server documents. The value is empty, or one or more comma-separated entries. Each entry is a port, an inclusive `start-end` range, or a mapping `[address:]external:internal`. In a mapping, each side is a port or a range, and the address is an IPv4 literal or a bracketed IPv6 literal. Every port SHALL be between 1 and 65535. A range's start SHALL NOT exceed its end. When both sides of a mapping are ranges they SHALL be the same length. The rejection SHALL name the setting and the reason, and nothing SHALL be written.

#### Scenario: A plain range is submitted

- **WHEN** `server-udp-ports` is submitted as `19140-19159`
- **THEN** it is accepted

#### Scenario: A mapping with an address is submitted

- **WHEN** `server-udp-ports` is submitted as `203.0.113.10:19132-19232:32000-32100`
- **THEN** it is accepted

#### Scenario: An empty value is submitted

- **WHEN** `server-udp-ports` is submitted empty
- **THEN** it is accepted, and the server chooses player ports from the operating system's range

#### Scenario: A malformed value is submitted

- **WHEN** `server-udp-ports` is submitted as `19159-19140` or `abc` or `19132-19140:32000-32100`
- **THEN** the write is rejected with a reason naming `server-udp-ports`
- **AND** the stored configuration is unchanged

### Requirement: A player UDP port setting split across lines is not rewritten

The Bedrock server combines `server-udp-ports` entries from every line that assigns it, unlike other settings, where the last assignment wins. Cobble SHALL report the value of such a setting as all its entries combined. Cobble SHALL reject a write to it while it is assigned on more than one line, with a reason telling the operator to combine the lines by hand, because rewriting one line would not produce the submitted value.

#### Scenario: The setting is split across lines

- **WHEN** the configuration assigns `server-udp-ports=19140-19149` and, on a later line, `server-udp-ports=19150-19159`
- **THEN** its reported value is `19140-19149,19150-19159`

#### Scenario: A write to a split setting

- **WHEN** a value is submitted for `server-udp-ports` while it is assigned on more than one line
- **THEN** the write is rejected with a reason naming `server-udp-ports`
- **AND** the stored configuration is unchanged

### Requirement: Configuration consistency is reported

Cobble SHALL check the saved configuration for combinations of settings that are each valid but conflict, and report each conflict as a warning. The player UDP port range being smaller than the player limit (see `server-network`) is such a conflict. A configuration read SHALL report the conflicts in the saved configuration. A write that changes any setting involved in a conflict SHALL be accepted and SHALL report the conflicts in the configuration as saved, whichever of the involved settings it changed.

#### Scenario: A read with a conflict

- **WHEN** the configuration is requested and the saved configuration contains a conflict
- **THEN** the conflict is reported, naming the settings involved

#### Scenario: The player limit is raised past the range

- **WHEN** the transport is `nethernet`, `server-udp-ports` is `19140-19149`, and `max-players` is changed to 20
- **THEN** the write is accepted
- **AND** the response reports the conflict

#### Scenario: The range is narrowed below the player limit

- **WHEN** `max-players` is 10 and `server-udp-ports` is changed to `19140-19144`
- **THEN** the write is accepted
- **AND** the response reports the conflict

#### Scenario: The conflict is resolved

- **WHEN** a write widens the range to cover the player limit
- **THEN** no conflict is reported by that write or by later reads
