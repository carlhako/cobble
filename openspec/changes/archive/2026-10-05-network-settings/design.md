# Design

## Context

See proposal.md (Why). The facts that shape the approach:

- `ConfigService.read()` builds one row per key **in the file**. The schema only decorates rows, so a recognised key the file lacks is invisible (`src/cobble/config/service.py`).
- The vendor `server.properties` for 1.26.51.1 ships `server-ip` commented out and does not mention `server-udp-ports` at all. The grammar comes from the vendor `bedrock_server_how_to.html`, section "UDP port configuration for NetherNet".
- `server-udp-ports` is the only known key that **accumulates** across lines ("the property may also appear on more than one line to accumulate entries"). `PropertiesDocument.get()` and `.effective()` are last-wins, and `.set()` rewrites the last line only.
- The schema is checked against the vendor file by `tests/config/test_schema.py` (`VENDOR_KEYS ⊆ SCHEMA`). Adding keys that are not vendor keys is allowed.
- The only existing cross-setting logic is the transport view (`transport_view()`), which already resolves the saved and running transport against the version's default.
- Sections are one entry each in `web/src/sections.tsx`.

## Goals / Non-Goals

**Goals:**
- One write path. The Network section saves through `POST /api/config`, so validation, maintenance refusal, pending detection and `allow-list` enforcement behave exactly as on the Configuration page.
- The network view is **derived** from the saved configuration, the running snapshot and the version default. It stores nothing of its own.
- Parse `server-udp-ports` once, in a module both the validator and the network view use.

**Non-Goals:**
- Anything to do with public addresses: no field, no detection, no display. A hand-written IP mapping is still valid and preserved.
- Removing keys from `server.properties`. Choosing "let the OS pick" writes an empty value, which the vendor docs list as the default.
- Showing the server's LAN address in the forwarding instructions. It is hard to pick reliably on a multi-homed host, so the text says "this server's LAN address".
- Showing the conflict banner on the Dashboard. It appears on Network and Configuration only.
- Opening the host firewall, or configuring UPnP or the router.

## Decisions

### D1. Unset recognised settings come from the schema at read time

`read()` returns file keys in file order, as now, then appends every schema key not in the file with `present: false` and `value = schema.default`. Reading never writes, and the existing "a setting is added" path of `write()` inserts the key when it is set.

- *Alternative*: seed missing keys into the file on startup or update. Rejected, because it writes to the operator's file without being asked, and it would conflict with `carry_vendor_defaults`, which assumes the file only holds keys the vendor or the operator put there.
- *Alternative*: special-case only the two network keys. Rejected, because a general rule also covers the next key BDS documents but doesn't ship.

The pending comparison needs no change. A key absent from both the file and the running snapshot has no difference.

### D2. A `udp_ports` module owns the grammar

`src/cobble/config/udp_ports.py` parses a value into entries `Entry(external: Range | None, internal: Range, address: str | None)`. It exposes `parse(value) -> list[Entry]`, which raises `ValueError` with a reason. It also exposes three derived views:
- `local_ports(entries)`: the union of the internal ranges, for the capacity check.
- `forward_ports(entries)`: the external side of each mapping, or the range itself for a plain entry.
- `form(value)`: `os` | `range(start, end)` | `custom`. It is `range` only for exactly one plain entry with no address.

Addresses are checked with `ipaddress` (IPv6 bracketed). The schema gains a per-key validator hook. `PropertySchema` gets an optional `check: Callable[[str], str | None]`, and `validate()` calls it for `STRING` entries, turning a returned reason into an `error` issue. `server-udp-ports` is the only user for now. This keeps the "a string never rejects" default for every other string key.

### D3. The accumulating key is read combined and written only when single-line

`PropertiesDocument` gains `values(key) -> list[str]` (every assignment, in order). `ConfigService` reads `server-udp-ports` as `",".join(non-empty values)`. This key-specific rule lives in a small `ACCUMULATING = {"server-udp-ports"}` set in the schema module, next to the schema. `write()` rejects a change to an accumulating key assigned on more than one line, with an `error` issue that tells the operator to merge the lines by hand. It is rejected rather than merged automatically because merging would rewrite lines the operator wrote, which the "preserves the rest of the file" requirement forbids.

### D4. Consistency checks run on the merged document

`consistency(effective: dict) -> list[ValidationIssue]` sits in the config package and is pure: a dict goes in, warnings come out. The single rule for now: transport resolves to `nethernet`, `server-udp-ports` parses to at least one entry, and `len(local_ports) < int(max-players)` gives a warning keyed `server-udp-ports` with a message naming both numbers. An unparseable `max-players` skips the rule, because type validation reports that already. Transport resolution reuses the version-default logic behind `transport_view()`.

- `read()` returns the check's result as a new top-level `conflicts` list. Every read carries it, so a hand edit shows up on the next read.
- `write()` runs the check on the post-apply document when `changes` touches any key in the rule's key set (`transport`, `max-players`, `server-udp-ports`). It adds the result to `warnings`, and the response also carries the full `conflicts` list. "Either way" falls out naturally, because whichever key changed, the merged result is checked.

### D5. The network view is a read-only endpoint

`GET /api/config/network` sits beside `/transport` in the config router, because it is a view over config. It returns:

```
{
  "transport": {value, saved, recommended, running, pending_restart, ...},  # TransportView
  "layout": "nethernet" | "raknet",       # the saved transport, resolved against the default
  "layouts": {                            # one per transport, so a draft switch can re-render
    "<transport>": {
      "settings": [{key, value, present, protocol, label}],
      "udp_range": {form: "os"|"range"|"custom", start?, end?, size?, value?, local?} | null,  # nethernet only
      "lan_discovery": {protocol: "udp", port: 7551} | null,
      "forward": [{protocol, ports, note?}],   # no UDP entry when the OS picks
      "pin_required": bool
    }
  },
  "conflicts": [...]
}
```

The layout of each transport is returned, not only the saved one, because the section's draft can switch transport before saving (D6) and must show that transport's settings from the saved values.

The endpoint has no writes. The section writes through `POST /api/config` and then re-reads.

- *Alternative*: a `POST /api/network` taking structured fields. Rejected, because it would be a second write path to keep in step with validation, maintenance and enforcement.

UDP 7551 is a constant observed on 1.26.51.1 (memory: bds-nethernet-transport). It is not configurable and is not documented by the vendor, so it lives in one place, labelled as observed.

### D6. The Network section keeps its own draft, and a custom range is left alone

`web/src/sections/Network.tsx` follows `Configuration.tsx`'s draft → save → re-read pattern. The transport selector is part of the draft, and switching it re-renders the layout from the draft value. Only keys in the visible layout, plus `transport`, are submitted. A `custom` range renders read-only and is never part of the submission, which satisfies "saving does not change it". The from/to inputs compose `start-end`, or `start` when the two are equal. "Let the OS pick" submits `""`.

Pending-restart and maintenance behaviour reuse the Configuration page's existing hooks and components, so the two sections cannot disagree.

### D7. One shared conflict banner

`ConflictBanner` renders `conflicts` from the config read. Both sections fetch through the same client call and render it at the top. After a save, each section re-reads, so the banner updates without a refresh.

### D8. Schema text

- `server-port`: "Port players connect to. Under NetherNet: TCP (handshake). Under RakNet: UDP (IPv4)."
- `server-portv6`: "UDP port for IPv6 players under RakNet. Ignored under NetherNet."
- New `server-ip` (string, default empty): "Local address to bind to under NetherNet. Empty binds all interfaces. Ignored under RakNet."
- New `server-udp-ports` (string with a check, default empty): "UDP ports for player connections under NetherNet. Empty lets the OS pick. Pin a range to forward it for external players."

## Risks / Trade-offs

- [External players may be unable to join without an IP prefix in `server-udp-ports`. The vendor docs say the server then advertises its own addresses, and whether NetherNet's WebRTC still finds the public address through STUN is untested.] → The live test on cobble-2 covers exactly this. If it fails, reopen the no-public-IP decision. The form's `custom` path already preserves a hand-written mapping in the meantime.
- [The capacity rule assumes one UDP port per player. That comes from reading the vendor docs ("allocates UDP ports for client connections") and has not been observed.] → The rule is a warning, never a rejection. The live test with two clients can confirm or drop it.
- [Appending every unset schema key lengthens the Configuration list.] → Today only `server-ip` and `server-udp-ports` are affected, because every other schema key is a vendor key present in a seeded file. The existing filter bar covers growth.
- [UDP 7551 could change in a later BDS.] → It is informational only, a single constant, and never used to open or forward anything.
- [`server-port` changes meaning with the transport, so a RakNet user forwarding "TCP 19132" from old notes would fail.] → The forwarding list is always derived from the saved transport, never from static text.

## Migration Plan

This change only adds fields and endpoints. No data migration is needed and the file is never rewritten on upgrade. Rollback is reinstalling the previous release. A `server-udp-ports` line written by this version stays valid for BDS and appears as an unrecognised row in older cobble.
