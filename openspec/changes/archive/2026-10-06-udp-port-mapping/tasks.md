# Tasks

## 1. `server-udp-ports` grammar (backend)

- [x] 1.1 Change `_address()` in `src/cobble/config/udp_ports.py` to accept RFC 1123 hostnames. A value of only digits and dots must still be valid IPv4, and bracketed IPv6 works as before (design D1). Update the module docstring to say hostnames were verified live but are not in the vendor docs. Verify in `tests/config/test_udp_ports.py`:
  - Accepted: `play.example.com:19140-19150:19140-19150`, `localhost:19140:19140`, and a 63-character label.
  - Rejected: `1.2.3.999:1:1`, `1.2.3:1:1`, `-bad.example:1:1`, `bad-.example:1:1`, `my_host:1:1`, `a..b:1:1`, `host.:1:1`, a 64-character label, a name over 253 characters, and an unbracketed IPv6 (still the "must be in brackets" message).
  - Every existing case still passes.
- [x] 1.2 Extend `Form` with `external: Range | None` and `address: str | None`, and make `form()` return `range` for any single parsed entry (design D2). Verify with unit tests:
  - `19140-19159` gives external `None` and address `None`.
  - `203.0.113.10:19132-19232:32000-32100` gives local 32000-32100, external 19132-19232 and that address.
  - `play.example.com:19140-19150:19140-19150` gives the hostname.
  - `19132:19140-19150` gives range with a single external port.
  - `19140-19149,19160-19169` and an unparseable value give `custom`.
- [x] 1.3 Add `forward_pairs(entries)`, which returns `(external or internal, internal)` per entry, in order and unmerged (design D3). Verify with unit tests for a plain entry, a mapping, and two entries.

## 2. Network view and schema text (backend)

- [x] 2.1 In `src/cobble/config/network.py`, add `external` (`{start, end}` or `null`) and `address` to `udp_range` for `form: "range"`. Verify in `tests/config/test_network.py` for a plain range, a mapping with an IP, and a mapping with a hostname.
- [x] 2.2 Build the UDP forward entries from `forward_pairs`, adding `to` only when the local ports differ from the external ones (design D3). Verify in `tests/config/test_network.py`:
  - `19132-19142:19140-19150` gives `{udp, 19132-19142, to: 19140-19150}`.
  - `play.example.com:19140-19150:19140-19150` gives `{udp, 19140-19150}` with no `to`.
  - Two entries give two UDP lines.
  - A plain range is unchanged from today.
- [x] 2.3 Relabel `server-ip` as "Bind address (this machine)", and update the `server-udp-ports` description in `src/cobble/config/schema.py` to mention mappings and hostnames (design D5). Verify that `tests/config/test_schema.py` and the network tests pass with the new label.
- [x] 2.4 Check the whole path through the API. Verify with `tests/api/` cases:
  - `POST /api/config` accepts `server-udp-ports=play.example.com:19140-19150:19140-19150`.
  - `GET /api/config/network` then reports the hostname address and the UDP forward entry.
  - With `max-players` above 11, the capacity conflict is reported for that value.

## 3. Network section (frontend)

- [x] 3.1 Extend the types in `web/src/api/client.ts`: `UdpRange` gains `external` and `address`, and the forward entry gains an optional `to`. Verify with `npm --prefix web run build`.
- [x] 3.2 In `web/src/sections/Network.tsx`, replace the draft's `from`/`to` with `address`, `localStart`, `localEnd`, `extStart` and `extEnd`. Fill them from `udp_range`, and compose the value as in design D4: collapse to the plain form, and bracket a bare IPv6 address. Verify in `web/src/test/network.test.tsx` that each row of the D4 table saves the expected value:
  - Local only: `19140-19150`.
  - Local and different external: `19132-19142:19140-19150`.
  - Hostname with external blank: `play.example.com:19140-19150:19140-19150`.
  - Bare IPv6: `[2001:db8::1]:19140-19150:19140-19150`.
  - External equal to local, no address: collapses to `19140-19150`.
  - Blank end boxes: single ports.
  - An untouched saved mapping sends nothing.
- [x] 3.3 Render the address field and the four port boxes with the labels and help text from design D5. Add inline checks (local start required, start not after end, equal sizes when both sides are ranges) that disable Save and show the reason beside the field. Verify in the network tests:
  - A size mismatch shows the message and disables Save.
  - A backend rejection of a bad address shows beside the field.
  - Opening a saved mapping fills every field.
- [x] 3.4 Show the hostname restart note while the address is a hostname, and hide it for an IPv4 or IPv6 address. Verify in the network tests with `play.example.com`, `203.0.113.10` and `2001:db8::1`.
- [x] 3.5 Show the translation in the forward panel (`UDP 19132-19142 -> 19140-19150 on this server`), add "Players reach you at <address>" when an address is set, and update the custom read-only text to "several entries or a value cobble can't parse". Verify in the network tests:
  - A mapping shows the arrow line and the address line.
  - A plain range shows neither.
  - A two-entry value is read-only and is not submitted on save.

## 4. Docs and checks

- [x] 4.1 Update the README network section (around the "from–to form" paragraph) to describe the address field, external and local ports, hostnames, and the restart note. Verify by reading the rendered section.
- [x] 4.2 Run the full suites. Verify that all of them pass:
  - `.venv/bin/pytest`
  - `ruff check` on changed files
  - `ruff format` on your own files only (a clean tree already fails `--check`)
  - `npm --prefix web test` and `npm --prefix web run build`

## 5. Live verification on cobble-2

- [x] 5.1 Deploy the branch to cobble-2 with a release tarball and `deploy/install.sh` (see the test-LXC notes). In the Network section, set a hostname address and save. Verify all of the following:
  - `server.properties` holds the composed mapping line.
  - The section shows the hostname in its field, the restart note, and the forward list with the translation.
  - After a restart, the BDS console log shows no `server-udp-ports` parse error.
- [x] 5.2 Restore cobble-2's previous `server-udp-ports` value (`19140-19150`) and confirm that the section shows it as a plain range again. Verify by reading `server.properties`.
