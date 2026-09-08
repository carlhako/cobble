## Why

M4 gave cobble a roster of everyone who has played on this server. It cannot do anything about any of them. When someone needs to be removed — the reason a family server operator opens a control panel at all — the only route is the console section, typing commands whose syntax and consequences are undocumented in the interface.

Every milestone since M3 has deferred this on the same stated grounds: moderation needs "a general console command/response layer that does not exist". **M5 built that layer** (`Console.query` — arbitrary command, arbitrary reply matcher, silent path), and **a spike against BDS 1.26.45.1 on the live host has established that moderation does not need it.** Every mutation has a file behind it, and going through the file beats driving the command on every axis: `allowlist add` fails outright on a gamertag containing a space, refuses to record an xuid even for a player it can see online, and cannot run at all while the server is stopped. The stated blocker was never the real one.

The real one is identity. `kick` targets a gamertag, `allowlist.json` is name-keyed with an optional xuid BDS never fills in, `permissions.json` is xuid-keyed with no name at all, and cobble's roster is keyed by the stable xuid. Cobble's roster is the only thing on the box that can join those four namespaces — which is also why it can write an allowlist entry carrying an xuid, something BDS itself will not do, making an entry survive a gamertag change.

The spike settled one more thing, and it decides the shape of the whole change: **Bedrock has no ban command.** `help ban` is a syntax error. Exclusion is the allowlist and nothing else — and removing a player from the allowlist does not disconnect them, verified with a live client still standing in the world afterwards. A "ban" that is one allowlist edit is a lie in two directions at once.

## What Changes

- **Ban is a composite action, because nothing smaller is honest.** Banning a player removes them from the allowlist, reloads it, ensures the allowlist is actually being enforced, kicks them, and records the ban. Each step was verified necessary: with the allowlist off (the shipped default) an allowlist edit excludes nobody, and with the player online an allowlist edit does not remove them.
- **The first ban is a server-wide access change, and is presented as one.** Turning the allowlist on excludes every player not on it. Cobble knows from the roster exactly who that is and names them before the operator commits, offering to carry them onto the list.
- **A ban is cobble's own record, not an inference from absence.** "Not on the allowlist" describes everyone who has never joined. `cobble.db` records who was deliberately excluded, when, why, and under what name — so unbanning has something to restore and the roster can distinguish exclusion from absence.
- **Kick, as a separate act.** Transient removal with no durable effect, confirmed by observing the player's disconnect on the existing event bus rather than by parsing the reply. A kicked session is recorded as such: the disconnect line is byte-identical to a voluntary leave, so the intent is registered before the command is sent, not inferred afterwards.
- **Operator rights are granted by writing `permissions.json`.** `permission set` succeeds *silently* — no acknowledgement, no error — so as with gamerules the write is confirmed by re-reading, never by the reply. Writing the file also lets cobble op a player who is offline, which the console command cannot do because it has no xuid to resolve.
- **`allow-list` stops having two masters.** `allowlist on` changes the running server without touching `server.properties`, and cobble's pending-vs-live panel is structurally blind to it — it compares the file against a spawn snapshot and never against the live server. Both are now written together, and cobble learns the live state by parsing the console lines that announce it. **BREAKING** to the `server-config` requirement that a saved setting is pending until the next start: `allow-list` is applied immediately as well.
- **The allowlist and permissions become readable state.** Both files are shown in the Players section, including the entries with no roster counterpart — someone added ahead of their first join — so the list is never a partial view of itself.

Not included: automatic moderation. BDS does not put player chat in stdout, so cobble cannot observe a reason to act; it is the instrument, never the detector, and every action here is operator-initiated. No time-limited or scheduled bans. No cross-server or shared ban lists. No IP-level blocking — Bedrock offers none. No editing of `permissions.json` beyond the three levels BDS defines, and no use of the `###*`-delimited JSON reply envelope the spike uncovered: the files are authoritative, and reading them needs no console traffic at all.

## Capabilities

### New Capabilities
- `server-access`: Who may join this server and what they may do once in — the allowlist and its enforcement state, operator permissions, cobble's durable ban record, and the composite ban and unban actions that keep the two files, the running server, and that record consistent with one another.

### Modified Capabilities
- `server-players`: The roster gains actions. A player can be kicked, banned, unbanned, and given or refused operator rights from their entry, and carries their current access state. A session ended by a kick is recorded with that reason rather than as an ordinary disconnect.
- `server-events`: The vocabulary gains the allowlist transitions the server announces (`Turned on/off the allowlist`) and its membership changes, so live enforcement state and out-of-band edits are observed rather than assumed.
- `server-config`: `allow-list` is no longer pending-only. Saving it applies to the running server as well as the file, and the setting's live value is reported from observation rather than from the file alone.
- `server-status`: Access state is reported — whether the allowlist is being enforced right now, and how that compares to what `server.properties` says.
- `web-ui-shell`: The Players section gains the moderation controls, the ban confirmation that names who else a first ban would exclude, and the allowlist and permissions views.

## Impact

**New code** — a `cobble/access/` package owning the two JSON documents and their atomic round-tripping, the ban store, and the service that composes ban/unban/kick/op and keeps file, server, and record consistent; an API router at `/api/access` plus moderation routes on the existing players router; ban and kick controls in `Players.tsx`.

**Modified code** — `cobble/events/patterns.py` and `model.py` (the allowlist events); `cobble/players/storage.py` and `recorder.py` (the kicked end reason and the pre-registered intent); `cobble/config/service.py` (`allow-list` applies live); `cobble/status/tracker.py` (the access block); `cobble/runtime.py` (wire the service to server-ready, as the gamerule manager already is); `web/src/sections/Players.tsx`.

**Dependencies** — none added.

**Data** — new tables in the existing `<state_dir>/cobble.db`, already inside the backup set. A new `end_reason` value is additive; existing sessions keep theirs. Nothing is migrated — an allowlist or permissions file cobble has never written is adopted as it stands, and a server with a populated allowlist and no ban history reports every entry as simply allowed, never as evidence of a past ban.

**Bedrock coupling** — this change writes two files BDS also writes, and parses console output that is undocumented and free to drift between versions. Two hazards are recorded with their verification in design.md: BDS writes literal `null` rather than `[]` into `allowlist.json` when the last entry is removed, and `permission set` reports neither success nor failure. Round-tripping preserves fields cobble does not recognise, as `server.properties` writes already do.

**Unaffected** — the supervisor's process model, the update and backup state machines, gamerule editing, `Console.query` (which this change does not use and does not extend), and the authentication posture. `auth_guard` remains the no-op seam and every new state-changing route depends on it, as the other routers do — worth noting that moderation is the first capability where the absence of authentication has consequences beyond the container.
