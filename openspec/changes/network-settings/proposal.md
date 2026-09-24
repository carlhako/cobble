# Proposal

## Why

Bedrock 1.26.51.1 switched to the NetherNet transport, and cobble has not caught up. Players now connect with a TCP handshake on `server-port`, then one UDP connection each, on a port the server picks from the OS's ephemeral range. External players can only reach the server if that UDP range is pinned with `server-udp-ports` and forwarded on the router. Cobble gives no way to set it: the setting is missing from the vendor `server.properties`, and the Configuration page only lists keys already in the file. On cobble-2 the only route was a hand-written `POST /api/config`. The panel also still calls `server-port` a "UDP port", which is wrong under NetherNet. Nothing tells the operator which ports to forward.

## What Changes

- A new **Network** section in the interface. It shows the network settings for the saved transport, which is the one the next start will use:
  - **NetherNet**: handshake port (TCP, `server-port`), bind address (`server-ip`), and the player UDP port range (`server-udp-ports`), shown as a from/to pair, with an option to let the OS pick. LAN discovery on UDP 7551 is shown for information.
  - **RakNet**: the IPv4 port (UDP, `server-port`) and the IPv6 port (UDP, `server-portv6`).
  - Either way, the section lists the ports to forward on the router for external players. Under NetherNet with no pinned range, it says to pin one instead, because an OS-picked range cannot be forwarded.
  - The transport can be switched from the section. When the saved transport differs from the running one, the section says a restart is needed.
  - Settings the current layout does not show are left untouched in the file.
  - A `server-udp-ports` value the range form cannot represent (a NAT mapping, an IP prefix, several entries) is shown read-only and is never overwritten by the form.
- A **UDP capacity check**. It applies when the transport is NetherNet and a UDP range is pinned, and fires when the range has fewer ports than `max-players`. It is checked when either setting is saved, whichever page saves it, and whenever the configuration is read. The result is a warning, not a rejection. The Network and Configuration sections show a banner at the top while the mismatch exists.
- **Settings missing from the file**: a setting cobble recognises that is absent from `server.properties` is still returned, marked as not set, with its default. It can be set from the Configuration section.
- **Schema additions**: `server-ip` and `server-udp-ports`. A malformed `server-udp-ports` is rejected.
- **Schema corrections**: `server-port` and `server-portv6` descriptions account for the transport. Under NetherNet `server-port` is TCP and `server-portv6` is ignored.
- **Out of scope**: no public-IP field, detection, or display. The operator can still write an IP-prefixed mapping by hand or through the API.

## Capabilities

### New Capabilities

- `server-network`: the network view derived from configuration. It covers the transport-dependent set of network settings, the ports external players need forwarded, the structured reading of `server-udp-ports`, and the UDP capacity check.

### Modified Capabilities

- `server-config`: recognised settings absent from the file are readable as not set. `server-udp-ports` values are validated against the vendor grammar. Writes and reads report the UDP capacity mismatch as a warning.
- `web-ui-shell`: a Network section is added. The configuration section shows recognised-but-unset settings and lets them be set. The capacity mismatch banner appears at the top of the Network and Configuration sections.

## Impact

- **Backend**: `src/cobble/config/schema.py` (new entries, corrected descriptions, `server-udp-ports` validator), `src/cobble/config/service.py` (unset recognised settings in `read()`, the capacity check on write and read), a new network view module, and `src/cobble/api/config.py` (or a new network router) to expose it. Tests go in `tests/config/` and `tests/api/`.
- **Frontend**: a new `web/src/sections/Network.tsx`, a `/network` entry in `web/src/sections.tsx`, "not set" rows and the mismatch banner in `web/src/sections/Configuration.tsx`, types in `web/src/api/client.ts`, and tests in `web/src/test/`.
- **API**: `GET /api/config` gains unset recognised settings and a list of consistency warnings. `POST /api/config` can return a capacity warning. A network view endpoint is added. All of these only add fields or endpoints.
- **Docs**: the README network transport section points to the Network section.
- **Live verification** on cobble-2 after implementation checks two things. First, that a pinned range is actually used, by looking at the per-client UDP socket while a client joins. Second, whether an external client can join without an IP prefix in `server-udp-ports`. If it cannot, the no-public-IP decision is revisited.
