## 1. The access documents

- [x] 1.1 Create the `cobble.access` package with a document type for `allowlist.json` — parse, round-trip, and serialise a list of entries, preserving any field cobble does not recognise (design.md D1); verify a test round-trips an entry carrying an unknown field and asserts the field and its value survive
- [x] 1.2 Fold an empty representation to an empty list on read — `null`, `[]`, an absent file, and an empty file — and always write `[]` for empty (design.md D8); verify a test reads the literal `null` form recorded in design.md Context and asserts an empty list with no exception, and that writing empty produces `[]`
- [x] 1.3 Report an unparseable allowlist as a condition rather than raising; verify a test with malformed content asserts the condition is reported and the file is left untouched
- [x] 1.4 Add the same document handling for `permissions.json`, preserving BDS's three-space indentation and spaced-colon formatting on write (design.md Context); verify a test round-trips a file in the verbatim BDS format from design.md Context and asserts a byte-identical result when nothing changed
- [x] 1.5 Write both documents atomically through the same temp-file-and-replace approach `server.properties` writes already use; verify a test asserts an interrupted write leaves the previous file intact
- [x] 1.6 Re-read before every write rather than caching, so an out-of-band edit is not clobbered by a stale view (design.md Risks); verify a test mutates the file between a read and a write and asserts the write is based on the newer content
- [ ] 1.7 Probe whether BDS preserves an `xuid` field cobble writes into an allowlist entry (design.md Open Questions); record the result in design.md Context and, if it is stripped, mark D4 as degraded to name-only  <!-- BLOCKED: live probe on cobble-2, belongs with section 10 -->


## 2. Allowlist enforcement state

- [x] 2.1 Add event types and patterns for the two enforcement announcements — `Turned on the allowlist` / `Turned off the allowlist` (design.md D5); verify a test parses both verbatim lines from design.md Context into the corresponding events and asserts each retains its source line
- [x] 2.2 Add event types and patterns for the membership announcements — `Added <name> to the allowlist` / `Removed <name> from the allowlist`; verify a test asserts both parse and that a name containing spaces is captured whole
- [x] 2.3 Track live enforcement state from those events, starting as unknown and never guessing; verify a test asserts the state is unknown before any observation and follows each event afterwards
- [x] 2.4 Assert the saved configuration's enforcement value to the running server on every server-ready, so a divergence self-heals within one start (design.md D5); verify a test asserts the command is issued at readiness and that the tracked state matches the file afterwards
- [x] 2.5 Make saving `allow-list` write the file and instruct the running server, and refuse to instruct the server if the file write failed; verify tests assert both halves happen on success and that a failed write issues no command
- [x] 2.6 Exclude `allow-list` from the pending-changes report and report the live-versus-saved comparison for it instead; verify tests assert it is never pending after a save while running, and that an out-of-band enforcement change is reported as a disagreement naming which value is in effect

## 3. The ban record

- [x] 3.1 Add a ban table to `cobble.db` recording the stable identifier, the name held at ban time, the reason, and the timestamp; verify a test opens a temporary database twice and finds the schema unchanged the second time
- [x] 3.2 Implement recording, lifting, and querying a ban, keyed by identifier; verify a test asserts a lifted ban stops being reported while its recorded name and reason remain retrievable
- [x] 3.3 Report ban state without inferring it from allowlist absence (design.md D3); verify a test asserts a player absent from the allowlist with no ban record is not reported as banned
- [x] 3.4 Keep a ban applicable across a display-name change; verify a test renames a player in the roster and asserts the ban still applies and the ban-time name is still reported
- [x] 3.5 Make every ban storage failure logged and non-raising, as player history writes already are; verify a test with a storage layer that raises asserts the server and the event pipeline are unaffected

## 4. Kick and session attribution

- [x] 4.1 Implement kick — send `kick <name> [reason]` through the echoed console path, resolving on an observed departure for that player within a bounded time (design.md D6); verify a test with a fake server asserts the command is echoed to console subscribers and that the result resolves on the disconnect event
- [x] 4.2 Register the kick intent for a player before the command is sent, bounded by a timeout (design.md D6); verify a test asserts the intent exists before the command reaches stdin
- [x] 4.3 Record a session closed under a registered intent as ended by a kick, and treat its duration as exact; verify tests assert a kicked departure records the kick reason and that an unregistered departure records as directly observed
- [x] 4.4 Expire an intent that no departure satisfies, so a later voluntary leave is not misattributed; verify a test departs after the bound and asserts the session records a directly observed end
- [x] 4.5 Report a kick with no observed departure as unconfirmed rather than failed, and distinguish the `No targets matched selector` case (design.md Context); verify tests cover both outcomes and assert neither is reported as a plain success
- [x] 4.6 Refuse a kick for a player who is not connected and when the server is not running, without sending anything; verify tests assert both refusals and that stdin is untouched

## 5. Permissions

- [x] 5.1 Implement reading permission records, joining each identifier to the name cobble's roster holds and reporting no name where the roster has none; verify tests cover both cases and assert an unknown identifier is still reported
- [x] 5.2 Implement writing a permission level — write the file, issue `permission reload`, then re-read and report what the file says (design.md D7); verify a test asserts the reported result comes from the re-read and not from any acknowledgement
- [x] 5.3 Confirm correctness against a silent write; verify a test whose fake server emits nothing for the change still reports the outcome correctly from the re-read
- [x] 5.4 Refuse a permission level BDS does not define, without writing; verify a test asserts the refusal carries a reason and the file is unchanged
- [x] 5.5 Support changing the level of a player who is not connected (design.md D1); verify a test asserts the write and reload happen for an offline player in the roster

## 6. Composite ban and unban

- [x] 6.1 Implement ban as the ordered composite — record, remove from the allowlist, reload, ensure enforcement, kick, confirm (design.md D2); verify a test asserts every step runs in order for an online player and that the recorded ban survives a failure of the kick step
- [x] 6.2 Write the allowlist entry for a roster player with both the stable identifier and the current name, and name-only for a player cobble has no identifier for (design.md D4); verify tests assert both forms and that the name-only case is reported as having no identifier
- [x] 6.3 Report which players enabling enforcement would exclude, computed from the roster against the allowlist, and require confirmation before applying it; verify a test with roster players absent from the allowlist asserts they are named and that nothing is applied without confirmation
- [x] 6.4 Support carrying the excluded players onto the allowlist as part of the same confirmed action; verify a test asserts they are added and enforcement is enabled together
- [x] 6.5 Apply only the durable half of a ban while the server is stopped, attempting no kick; verify a test asserts the ban is recorded and the allowlist written with no command issued
- [x] 6.6 Implement unban — restore the player to the allowlist and clear the record, leaving enforcement as it stands (design.md D5); verify tests assert the player is re-added, the ban is cleared, and no enforcement command is issued
- [x] 6.7 Report each part of a completed composite that was carried out; verify a test asserts the report names the steps taken for both the online and stopped-server cases
- [x] 6.8 Refuse allowlist, permission, and ban writes during maintenance while keeping reads available (design.md D9); verify tests assert a write raises the maintenance error naming the operation and that a read succeeds

## 7. The HTTP interface

- [x] 7.1 Add an `/api/access` router exposing the allowlist, permissions, enforcement state, and ban records for reading; verify tests assert each shape, including the empty and unreadable cases
- [x] 7.2 Add the state-changing access routes — allowlist add/remove, permission set, enforcement on/off — each depending on `auth_guard` as the other state-changing routers do; verify a test asserts every new state-changing route carries the dependency
- [x] 7.3 Add the moderation routes on the players router — kick, ban, unban — addressed by stable identifier; verify tests assert an action reaches the intended player and that an identifier with no recorded sessions is refused
- [x] 7.4 Map refusals to distinguishable error codes — maintenance in progress, server not running, player not connected, unknown player, invalid permission level, confirmation required; verify tests assert each code and status
- [x] 7.5 Return the exclusion preview from the ban route when confirmation is required, rather than applying the ban; verify a test asserts the unconfirmed request applies nothing and returns the affected names

## 8. Status

- [x] 8.1 Add the access block to the status snapshot — enforcement in effect, the saved value, and the ban count; verify a test asserts the block appears and that an unobserved enforcement state is reported as unknown
- [x] 8.2 Report the stopped-server case as the value the next start will apply, distinguishable from an observed live state; verify a test asserts the two are distinguishable
- [x] 8.3 Push an updated status when enforcement changes; verify a test asserts a subscriber receives a new snapshot after an enforcement event

## 9. The web interface

- [x] 9.1 Add the moderation actions to a player's roster entry, with kick unavailable for an offline player and while the server is stopped; verify component tests assert the available actions in each state
- [x] 9.2 Present each player's access state — permitted, banned with reason and time, permission level — alongside their history; verify a component test asserts a banned player shows the reason and time and that an unbanned player absent from the allowlist does not read as banned
- [x] 9.3 Present the ban confirmation naming who else enabling enforcement would exclude, with the option to carry them onto the list; verify a component test asserts the names appear and that nothing is submitted until confirmed
- [x] 9.4 Present the allowlist and permission records, including entries with no roster counterpart and records with no known name; verify component tests assert both are shown rather than omitted
- [x] 9.5 Present live enforcement separately from the saved setting, including the unknown state; verify a component test asserts a disagreement shows both values and identifies which is in effect
- [x] 9.6 Present moderation as unavailable during maintenance with its reason, restoring it without a reload when maintenance ends; verify a component test drives a maintenance snapshot and asserts both transitions
- [x] 9.7 Reflect a completed action without an operator reload, and present a refusal against the player it concerns; verify component tests cover both

## 10. Live verification on cobble-2

- [ ] 10.1 Deploy the branch to cobble-2 and confirm the allowlist and permissions read correctly against the real files, including a server whose allowlist has been emptied to the `null` form by BDS itself; verify both read as empty with no error
- [ ] 10.2 Ban a connected player end to end with the live bot client and verify they are disconnected, absent from the allowlist, recorded as banned, and unable to rejoin while enforcement is on
- [ ] 10.3 Verify the exclusion preview names the right players by banning on a server whose roster contains players absent from the allowlist
- [ ] 10.4 Unban that player and verify they rejoin, and that enforcement was not changed by the unban
- [ ] 10.5 Kick a connected player and verify the session is recorded as ended by a kick with an exact duration, and that a voluntary leave in the same session history is not
- [ ] 10.6 Grant and remove operator rights on an offline player and verify the change survives a server restart
- [ ] 10.7 Change enforcement from the console section directly and verify cobble reports the live state and the disagreement with `server.properties`, then verify the next server start reconciles it
