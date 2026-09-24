# Spec Delta

## ADDED Requirements

### Requirement: Re-running the installer upgrades in place

Running the installer on a host where cobble is already installed SHALL upgrade cobble to the selected release in place. It SHALL replace the application and its service definition, restart the service so the new version runs, and leave the Bedrock installation, the world, cobble's state directory, and the backup destination untouched.

#### Scenario: Installer re-run on an existing deployment

- **WHEN** the installer is run on a host with cobble already installed
- **THEN** the selected release's cobble is installed and running afterwards
- **AND** the world, the Bedrock installation, cobble's state, and existing backups are unchanged

#### Scenario: A specific release is selected

- **WHEN** the installer is run with a specific release version selected
- **THEN** that release is installed rather than the latest

### Requirement: The installer provides the privileged upgrade helper

The installer SHALL install and enable the privileged upgrade helper so that later upgrades can be requested from the interface. The helper SHALL be triggered only by an upgrade request that cobble records in its own state directory, and SHALL NOT run otherwise.

#### Scenario: Fresh install or upgrade

- **WHEN** the installer completes
- **THEN** the upgrade helper is installed and armed
- **AND** cobble reports one-click upgrade as available

#### Scenario: No request pending

- **WHEN** no upgrade request has been recorded
- **THEN** the helper does not run
