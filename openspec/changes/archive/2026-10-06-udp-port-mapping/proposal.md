# Proposal

## Why

The Network section can only pin a plain local UDP range. Players behind a home router often need more than that: a port mapping (external ports on the router that differ from the local ones the server binds) and the address players reach, which is often a dynamic-DNS hostname. Bedrock supports both through `server-udp-ports` (`[address:]external:internal`). An operator hand-wrote a hostname prefix on 1.26.51.1, and a player outside the LAN joined, so BDS resolves hostnames itself. Cobble currently rejects that working value. The Configuration page refuses to save it, the Network section shows it read-only, the forwarding list drops its UDP entry, and the capacity check skips it.

## What Changes

- **Hostnames in `server-udp-ports`**: the address prefix of a mapping may be a hostname as well as an IPv4 or bracketed IPv6 literal. Cobble checks the hostname's syntax only, with no DNS lookup; whether it resolves is up to the operator. A dotted all-numeric address still has to be a valid IPv4 address.
- **The Network section edits a single mapping**: the player UDP ports form gains an address field (IP address or hostname, optional) and four port boxes: local start and end, external start and end.
  - Blank external boxes mean the same ports as local. A blank end box means a single port.
  - The form composes the shortest value that says the same thing. With no address and external equal to local, it writes a plain range as today.
  - A bare IPv6 address gets brackets added.
  - A hostname shows a note: if its IP address changes, the server may need a restart to pick up the new address.
- **What the form can edit**: any value with exactly one entry. Values with several entries, or that don't parse, stay read-only and are never overwritten by the form.
- **The forwarding list shows the translation**: a mapped UDP range is listed as external -> local on this server (for example `UDP 19132-19142 -> 19140-19150`). When an address is set, the section names it as the address players reach.
- **Labels**: `server-ip` becomes "Bind address (this machine)", to tell it apart from the address players reach.
- **Out of scope**: DNS lookup or reachability testing, public-address detection, and editing several entries in the form.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `server-config`: the `server-udp-ports` grammar accepts a hostname as the mapping address.
- `server-network`: the structured reading of `server-udp-ports` covers any single entry (local ports, optional external ports, optional address). The ports to forward pair each external range with its local range.
- `web-ui-shell`: the Network section edits the address and the external and local ports, shows the hostname restart note, and may show and request the address players reach. It still does not detect or look one up.

## Impact

- **Backend**: `src/cobble/config/udp_ports.py` (hostname addresses, single-entry form, external/local pairs for forwarding), `src/cobble/config/network.py` (the `udp_range` view gains `external` and `address`, forward entries gain `to`, and the `server-ip` label changes), and the `server-udp-ports` description in `src/cobble/config/schema.py`. Tests in `tests/config/` and `tests/api/`.
- **Frontend**: `web/src/sections/Network.tsx` (the address field and four port boxes, composition, inline size checks, the restart note, and the forward translation), the types in `web/src/api/client.ts`, and tests in `web/src/test/`.
- **API**: `GET /api/config/network` only adds fields. `udp_range` with `form: "range"` keeps `start`, `end` and `size` as the local side, and now also covers mappings. `POST /api/config` accepts values it used to reject.
- **Docs**: the README network section mentions mappings and hostnames.
