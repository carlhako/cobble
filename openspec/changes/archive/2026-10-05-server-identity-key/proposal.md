# Proposal

## Why

Under NetherNet, BDS proves its identity to clients during the TLS handshake on `server-port`, using the key at `keys/server_identity_key.pem`. Without a saved key, BDS generates a new one in memory on every start, so the vendor docs warn that players "have to re-accept server trust" after each restart. cobble restarts BDS for setting changes, Bedrock updates, restores and crash recovery, so on a default install every one of those can change the identity. A live check on cobble-3 (1.26.52.3) found no saved key (`serveridentity status`: "No saved server identity key exists"). Nothing in cobble shows this or saves a key.

## What Changes

- cobble reports whether a saved server identity key exists, read from the file in `data/` and not by sending a console command.
- When BDS is running without a saved key, cobble saves the **running** identity once (`serveridentity save`). Players who already trust the server keep working, and later restarts reuse the key. cobble does this once and never overwrites a saved key, including one the operator supplied.
- The Network section shows the identity state ("saved" or "not saved, changes on every restart") next to the transport settings, with a short explanation. While the server is running without a saved key, which happens only if the automatic save failed, it offers a "Save current identity" action to retry. While the server is stopped, it says the identity will be saved at the next start. `serveridentity save` needs a running server.
- A saved key is ordinary content of `data/`, so it is already captured and restored by backups. Restoring a backup taken before the key existed removes it. The next start then saves a new identity, so players accept the server again once.

## Capabilities

### New Capabilities
- `server-identity`: reporting whether the BDS server identity key is saved, saving the running identity once when no key exists without ever replacing an existing one, and showing that state and the manual save in the Network section.

### Modified Capabilities
<!-- None. The Network section and its view are introduced by the in-progress `network-settings` change, which must land first; this change adds to that section rather than altering an archived requirement. -->

## Impact

- **Backend**: the network view (`src/cobble/config/network.py`, `GET /api/config/network`) gains an `identity` block. A post-start step in the supervisor runs `serveridentity save` and confirms the save by reading the file. A new action endpoint does the manual save, refused during maintenance like other writes.
- **Frontend**: `web/src/sections/Network.tsx` and the `NetworkView` type in `web/src/api/client.ts`.
- **Files**: BDS writes `data/keys/server_identity_key.pem`. `keys/` is not vendor payload, so it stays a real directory in `data/` and Bedrock updates never touch it.
- **Security**: the PEM is an unencrypted private key, and backups are downloadable as a single file, so a downloaded backup will now contain the server's identity key. Document this, and keep the file mode no more permissive than BDS creates it.
- **Dependency**: builds on `network-settings`. That change should be archived first, or be applied alongside this one.
- Doesn't fix outside players being unable to connect. It removes one cause of handshake failures after a restart.
