# Design

## Context

See proposal.md (Why). The current state that shapes the approach:

- `src/cobble/config/udp_ports.py` already parses the full vendor grammar into `Entry(internal, external, address)`. Only `_address()` is narrower than BDS: it accepts IPv4 and bracketed IPv6 literals only.
- `form(value)` returns `os` | `range` | `custom`. It returns `range` only for one plain entry. The Network view (`src/cobble/config/network.py` `_udp_range`) passes that through as `udp_range: {form, start, end, size}`. Everything else is `custom`, shown read-only.
- `forward_ports()` merges the external side of every entry into sorted ranges, so it loses the pairing between external and local ports.
- Every consumer catches the parser's `ValueError` quietly, so a hostname prefix currently drops the UDP forward entry and skips the capacity check, with no error shown.
- The Network section (`web/src/sections/Network.tsx`) composes the value client-side and saves through `POST /api/config` (archived network-settings design, D6). The "a custom value is never submitted" guarantee is enforced client-side through `savedUdp()` returning `null`.

## Goals / Non-Goals

**Goals:**
- One grammar in one place: the hostname rule lives in `udp_ports._address()`, so the validator, the view and the capacity check all accept it together.
- Keep the one write path. The form still composes a string and saves it through `POST /api/config`.
- Only add API fields. Current clients that read `udp_range.start/end/size` keep working.

**Non-Goals:**
- Name resolution of any kind: on save, on read, or before start.
- Editing several entries, or accumulated lines, in the form.
- Restricting the single-port-external-to-local-range shape (`19132:19140-19150`). The vendor grammar allows it, so cobble accepts it as well.

## Decisions

### D1. Hostname syntax check, no lookup

`_address(text)` checks in this order:
1. Bracketed: an IPv6 literal, as today.
2. Only digits and dots: must parse as `IPv4Address`. Otherwise it is rejected as "not an IPv4 address", so a typo like `1.2.3.999` is never taken as a hostname.
3. Otherwise, a hostname under RFC 1123: at most 253 characters, labels of 1-63 characters from `[A-Za-z0-9-]`, no label starting or ending with `-`, and no trailing dot. Underscores are rejected.

An unbracketed IPv6 address still fails, with the existing "must be in brackets" message, because a hostname never contains `:`.

- *Alternative*: resolve the hostname on save and store the IP. Rejected, because BDS resolves the name itself (verified live), and storing an IP defeats dynamic DNS.
- *Alternative*: a lookup that only warns. Rejected at the operator's request. A slow or failing DNS call in the save path costs more than it catches.

### D2. `form()` covers any single entry

`Form` gains `external: Range | None` and `address: str | None`. It also keeps `start`/`end` as the local side. `form()` returns `range` for **any** single parsed entry, not just plain ones. It returns `custom` for several entries or a value that does not parse.

The view's `udp_range` for `form: "range"` becomes `{form, start, end, size, external: {start, end} | null, address: str | null}`.

- *Alternative*: a new `form: "mapping"` kind. Rejected, because `start/end/size` mean the same in both cases (the local ports). One kind keeps the frontend to one editable branch and adds fields without breaking existing clients.

### D3. Forward entries pair external with local

A new `udp_ports.forward_pairs(entries) -> list[tuple[Range, Range]]` returns `(external or internal, internal)` per entry, in entry order, unmerged. `_layout()` builds a UDP forward entry `{protocol: "udp", ports: str(external)}` from each pair, and adds `to: str(internal)` only when the two differ. `forward_ports()` stays for any caller that wants merged ranges.

Merging is dropped for the forward list because a merged external range no longer says which local ports it goes to. With several entries, one line per entry matches what the operator types into the router.

### D4. Client-side composition and validation

The draft replaces `from`/`to` with `address`, `localStart`, `localEnd`, `extStart` and `extEnd`. `composeUdp(d)` works like this:

```
local = localEnd blank or == localStart ? localStart : `${localStart}-${localEnd}`
ext   = extStart blank ? local : (extEnd blank or == extStart ? extStart : `${extStart}-${extEnd}`)
addr  = trim(address); if it contains ":" and has no "[", wrap it as `[addr]`
value = addr ? `${addr}:${ext}:${local}`
      : ext == local ? local
      : `${ext}:${local}`
```

Loading a saved entry fills every field from `udp_range`. The external fields are filled only when `udp_range.external` is non-null, so a saved plain range shows them blank.

Inline checks block Save (the button is disabled with the reason shown beside the field):
- Local start is required.
- Each side's start must not be after its end.
- If both sides are ranges, they must have the same size.

The backend validator is still the authority. Its error is shown beside the field as today. Address syntax is not checked client-side, which keeps the grammar in one place (D1); a bad address comes back as the backend's reason.

The hostname restart note appears while the trimmed address is non-empty, is not an IPv4 literal, and contains no `:`. A plain regex is enough, because the note is only advice.

### D5. Labels and text

- `network.py` `_LAYOUTS`: the `server-ip` label becomes "Bind address (this machine)".
- The new field is labelled "Address players reach", with the help text "IP address or hostname. Leave blank to advertise this machine's own addresses."
- The forward panel renders `UDP 19132-19142 -> 19140-19150 on this server` when `to` is present. When `udp_range.address` is set, it adds the line "Players reach you at <address>".
- The custom read-only text drops "a NAT mapping, an address" and now reads "several entries or a value cobble can't parse".
- The `server-udp-ports` schema description mentions mappings and hostnames.

## Risks / Trade-offs

- [The hostname support rests on one live join (2026-10-06, the operator's server). The vendor docs only describe IP literals.] → Cobble accepts what BDS was seen to accept and checks syntax only. A future BDS that rejects hostnames would fail at start, with the error in the console, and the form can switch back to an IP.
- [BDS probably resolves the hostname once at start, so a dynamic-DNS change during a long session may not be picked up.] → This is not verified. The form's restart note covers it, and the operator chose that over cobble-side resolution.
- [RFC 1123 rules may reject a name BDS would take (an underscore, a trailing dot).] → The rejection is visible and names the reason. Relaxing it later only means accepting more.
- [`19132:19140-19150` (single external, local range) is accepted, but how BDS behaves with it is untested.] → It follows the vendor grammar. The forward panel shows exactly what is configured.
- [Changing `form: "range"` to cover mappings could surprise an external API client that assumed `range` meant "plain".] → The API is the panel's own. The new fields are additive, and `start/end/size` keep their meaning (the local ports).

## Migration Plan

No data migration. A value that cobble used to show as `custom` (a single mapping) now opens in the form. Values that failed to parse before (hostname prefixes) now parse, so the forward list and the capacity check start covering them. Rollback is reinstalling the previous release. Older cobble shows a hostname mapping as custom and read-only and leaves it untouched.
