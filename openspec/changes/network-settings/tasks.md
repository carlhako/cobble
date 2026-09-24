# Tasks

## 1. `server-udp-ports` grammar (backend)

- [x] 1.1 Create `src/cobble/config/udp_ports.py` with `parse(value) -> list[Entry]` for the vendor grammar: a port, a `start-end` range, or `[address:]external:internal`; comma-separated entries; IPv4 or bracketed IPv6 addresses checked with `ipaddress`; ports 1-65535; start ≤ end; equal-length ranges on both sides of a mapping; empty → `[]`. It raises `ValueError` with a reason (design D2). Verify with `tests/config/test_udp_ports.py`, which covers every vendor example plus `19159-19140`, `abc`, `0`, `65536`, `19132-19140:32000-32100`, `1.2.3:1:1`, and an unbracketed IPv6.
- [x] 1.2 Add `local_ports(entries)`, `forward_ports(entries)` and `form(value)` (`os` | `range(start, end)` | `custom`). Verify with unit tests: `19140-19159` → range of size 20; `19140` → range of size 1; `203.0.113.10:19132-19232:32000-32100` → custom, with local 32000-32100 and forward 19132-19232; `19140-19149,19150-19159` → custom with 20 local ports.

## 2. Schema (backend)

- [x] 2.1 Add an optional `check` callable to `PropertySchema` and call it from `validate()` for `STRING` entries, turning a returned reason into an `error` issue (design D2). Verify with a `tests/config/test_schema.py` case showing that a string without a check still accepts anything.
- [x] 2.2 Add `server-ip` (string, default empty) and `server-udp-ports` (string, default empty, check = `udp_ports.parse`), and add an `ACCUMULATING = {"server-udp-ports"}` set. Rewrite the `server-port` and `server-portv6` descriptions to depend on the transport (design D8). Verify with schema tests: a malformed `server-udp-ports` is rejected, a valid one and an empty one are accepted, and `test_schema_entries_are_internally_consistent` still passes.

## 3. Configuration service (backend)

- [x] 3.1 Add `PropertiesDocument.values(key)` returning every assignment in order. Verify in `tests/config/test_properties.py`.
- [x] 3.2 Make `read()` append recognised keys absent from the file, with `present: false` and the default as the value, after the file's keys, and add `present` to `Setting.to_dict()` (design D1). Verify in `tests/config/test_service.py` that a file without `server-udp-ports` reports it as not set, that reading leaves the file byte-identical, and that a write of the key adds it and the next read reports it present.
- [x] 3.3 Report an accumulating key as its non-empty assignments joined with `,`, and reject a write to it while it is assigned on more than one line, with an error naming the key (design D3). Verify with a service test for the two-line read value, and a test that the rejected write leaves the file unchanged.
- [x] 3.4 Add a pure `consistency(effective, recommended_transport) -> list[ValidationIssue]` with the UDP capacity rule (design D4). Verify with unit tests for nethernet with a small range (warning naming 5 ports and 10 players), a range that covers the limit, no range, raknet with a small range, transport absent (falls back to the recommended transport), and a non-integer `max-players` (skipped).
- [x] 3.5 Return `conflicts` from the read path. In `write()`, when the changes touch `transport`, `max-players` or `server-udp-ports`, run the check on the post-apply document and add the result to `warnings`; the write response also carries `conflicts`. Verify with service tests: raising `max-players` past the range and narrowing the range below `max-players` each give an accepted write with the warning, and widening the range clears `conflicts` on the write and on the next read.
- [x] 3.6 Confirm the pending comparison ignores keys absent from both the file and the running snapshot. Verify with a test in `tests/config/test_snapshot_and_pending.py`.

## 4. Network view and API (backend)

- [x] 4.1 Build the network view (design D5) from the saved configuration, `transport_view()` and the `udp_ports` helpers. It covers the settings for each transport, each with its protocol label, the `udp_range` form, `lan_discovery` (the UDP 7551 constant, NetherNet only), `forward`, `pin_required` and `conflicts`. Verify with unit tests for: nethernet with a range (forward TCP 19132 + UDP 19140-19159); nethernet with the OS picking ports (`pin_required`, no UDP forward); a nethernet custom mapping (forwards the external ports); raknet (UDP 19132, and UDP 19133 marked IPv6-only; no `server-ip` and no range); and transport absent (resolves to the version default).
- [x] 4.2 Add `GET /api/config/network` to `src/cobble/api/config.py`, and make `GET /api/config` and `POST /api/config` return `conflicts`. Verify in `tests/api/test_config.py` with the response shapes, a `server-udp-ports` rejection returned as a per-key error, and a capacity warning returned from a `max-players` write.

## 5. Configuration page (frontend)

- [x] 5.1 Extend the `web/src/api/client.ts` types: `present` on a setting, `conflicts` on read and write results, a `NetworkView` type, and `getNetwork()`. Verify with `npm --prefix web run build`.
- [x] 5.2 Render settings that aren't set in `Configuration.tsx` with a "not set" badge and the default shown, save them like any other row, and send nothing for them unless edited. Verify in `web/src/test/configuration.test.tsx`: a row that isn't set shows the badge, an untouched save doesn't include it, and an edited save sends it.
- [x] 5.3 Add a shared `ConflictBanner` component and render it at the top of the Configuration section from `conflicts`, refreshed after each save. Verify with tests: the banner appears when the read has a conflict, and it appears and then clears when saves introduce and then resolve one.

## 6. Network section (frontend)

- [x] 6.1 Create `web/src/sections/Network.tsx` and register `/network` ("Network") in `web/src/sections.tsx`. Show the transport selector, and per transport the settings with protocol labels, LAN discovery (NetherNet only), and a "Forward on your router to this server's LAN address" list, or the pin-a-range message. Verify with a new `web/src/test/network.test.tsx` covering the NetherNet and RakNet layouts, the nav entry, and that no public-address field exists.
- [x] 6.2 Build the editing draft: the from/to inputs compose `start-end` (or `start` when they are equal); "Let the OS pick" submits `""`; switching the transport re-renders the layout; only visible keys and `transport` are submitted; a `custom` range is read-only, links to Configuration, and is never submitted (design D6). Verify with tests for pinning a range, choosing OS-picked ports, a transport switch submitting only `transport`, a custom value never being in the request, and a rejected value keeping the draft with the per-field reason.
- [x] 6.3 Reuse the pending-restart prompt and the maintenance read-only behaviour, and render `ConflictBanner` at the top. Verify with tests for: saving while running shows the restart offer; maintenance hides Save; narrowing the range below `max-players` shows the banner here, and the Configuration section shows it too.

## 7. Docs and checks

- [x] 7.1 Update the README's "Network transport" section and requirements table to point to the Network section for pinning the UDP range and for which ports to forward. Add a `CHANGELOG.md` entry under an unreleased heading. Verify by review.
- [x] 7.2 Run the full suites: `.venv/bin/pytest`, `ruff check` on changed files, `ruff format` on your own files only (a clean tree already fails `--check`), and `npm --prefix web test` plus `npm --prefix web run build`. Verify that all of them pass.

## 8. Live verification on cobble-2 (needs the operator's Windows client)

- [ ] 8.1 Deploy the branch to cobble-2 with a release tarball and `deploy/install.sh` (see the test-LXC notes). In the Network section, pin `19140-19159`, save and restart. Verify that `server.properties` has the line, and that `ss -uapn` shows `bedrock_server` on a port in 19140-19159 while the operator joins from Windows.
- [ ] 8.2 With the operator, set up router forwarding for TCP 19132 and UDP 19140-19159 to 10.0.1.165. Have a client outside the LAN (for example a phone on mobile data) join **without** an IP prefix in `server-udp-ports`. Record the result in the design's risks section; if the join fails, stop and revisit the no-public-IP decision before archiving.
- [ ] 8.3 If a second client is available, have two clients join at once and check `ss -uapn`. The check passes if there is one UDP port per player, which confirms the capacity rule; otherwise note the result and change or drop the rule.
