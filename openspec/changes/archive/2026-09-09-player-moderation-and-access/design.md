## Context

See proposal.md — Why. This design rests on a spike run against BDS **1.26.45.1** on the live host (cobble-2), driven through cobble's own console API, with a real authenticated client in the world for the player-facing probes. The observed facts, all of which the design below depends on:

| Probe | Result |
|---|---|
| `help ban` | `Syntax error: Unexpected "ban"` — **there is no ban command**, not even a help topic |
| `help kick` | `/kick <name: target> <reason: message>` — targets by **name**; the reason is optional in practice |
| `kick <online player> <reason>` | `Kicked <name> from the game: '<reason>'` — one line, then an ordinary `Player disconnected:` line ~5ms later |
| `kick <unknown>` | `No targets matched selector` + `Could not find player <name>` — two lines, only the first prefixed |
| `allowlist on` | `Turned on the allowlist` — **`server.properties` unchanged**; cobble's `config.pending` stayed `false` |
| `allowlist off` | `Turned off the allowlist` |
| (any) read of live on/off state | **none exists** — `allowlist list` returns members, never whether enforcement is on |
| `allowlist add <name>` | `Added <name> to the allowlist`; file gains `{"ignoresPlayerLimit":false,"name":"<name>"}` — **never an xuid**, even for a player online at the time |
| `allowlist add Some Player With Spaces` | `Syntax error: Unexpected "Player"` — **breaks on any gamertag containing a space** |
| `allowlist remove <last entry>` | `Removed <name> from the allowlist`; file becomes **literal `null`**, not `[]` (reproduced twice) |
| `allowlist remove` + `reload`, player online, allowlist on | player **stays online** — an allowlist edit never disconnects anyone |
| `allowlist reload` | `Allowlist reloaded from file.` — one line |
| `permission reload` | `Ops reloaded from file.` + `Permissions reloaded from file.` — two lines |
| `permission set <player> <level>` | **no output at all** — neither acknowledgement nor error; the write succeeded |
| `permission <level> <player>` / `ops <player> <level>` | syntax errors — the action comes first; `PermissionsAction` is `list` \| `reload` \| `set` |
| `permission list` | two `###*`-delimited JSON blocks: `{"command":"ops","result":["<xuid>"]}` and `{"command":"permissions","result":[{"permission":"operator","xuid":"<xuid>"}]}` |
| `allowlist list` | one such block; `"result":null` when the list is empty |
| `gamerule` | *not* enveloped — the `###*` wrapper is specific to these list commands |

`permissions.json` as BDS writes it is pretty-printed with three-space indent and spaced colons (`"permission" : "operator"`). `allowlist.json` is written compact.

Constraints inherited from earlier milestones:

- **Cobble's roster is keyed by the stable xuid** (M4), and holds the name as seen at each session. It is the only join between the four identity namespaces this change touches.
- **`Console.query` exists** (M5) — arbitrary command, arbitrary matcher, silent path, one line returned.
- **`Console.submit_command` echoes to every client**, by specification.
- **A maintenance interlock exists** (`MaintenanceInProgressError`), and every maintenance operation stops the server first (cold capture).
- **`cobble.db` exists** and is inside the backup set, checkpointed before capture.
- **Supervisor hooks exist** for server-ready and pre-stop; the player recorder and gamerule manager both use them.
- **`allowlist.json` and `permissions.json` are real files in `data/`**, survive a version swap, and are in every backup. Cobble has never read or written either.

## Goals / Non-Goals

**Goals:**

- Removing someone from the server actually removes them, in both senses — gone now, and unable to return — with no step the operator has to know to perform separately.
- The operator sees the full consequence of a ban before committing to it, including the consequence to people who are not the target.
- Cobble's picture of who may join survives the things that diverge it: an operator typing in the console, a restart, a restore.
- Every file this change writes round-trips fields cobble does not recognise, as `server.properties` writes already do.
- The Bedrock formats and hazards relied on are confined to one module and recorded above, so a version that changes them fails somewhere diagnosable.

**Non-Goals:**

- Extending `Console.query` to multi-line replies. Not needed — see D1 and D10.
- Any use of the `###*` JSON envelope. The files are authoritative and need no console traffic to read.
- Detecting misbehaviour. BDS does not put chat in stdout; every action here is operator-initiated. See Open Questions.
- A general permissions model of cobble's own. BDS defines three levels; cobble presents those and nothing more.
- Undoing a ban's *side effects* — a ban that turned the allowlist on does not turn it back off on unban. See D5.

## Decisions

### D1: The files are the interface; commands are for what has no file

Cobble reads and writes `allowlist.json` and `permissions.json` directly, atomically, preserving unrecognised fields — then issues `allowlist reload` or `permission reload` so a running server picks the change up. Console commands are used for exactly three things that have no file behind them: those two reloads, and `kick`.

*Why:* every property of the command path is worse. `allowlist add` fails outright on a gamertag containing a space (verified) and real gamertags contain spaces. It never records an xuid, even for a player online at that moment (verified), so a command-built allowlist is not rename-proof. It cannot set `ignoresPlayerLimit`. It cannot run at all while the server is stopped, whereas a file write applies at the next spawn for free. And `permission set` needs a target BDS can resolve to an xuid, so the console cannot op an offline player — while cobble, holding the xuid in its roster, can.

*Consequence:* the multi-line reply shapes the spike found (`###*` envelopes, two-line reloads) never need parsing, and this change adds nothing to the console layer.

*Alternative rejected:* driving the commands and reading the `###*` JSON back. It is genuinely well-formed machine-readable output, and it is still the weaker path for every reason above.

### D2: Ban is one composite action, and each step is verified necessary

`ban(player, reason)` performs, in order: record the ban → write `allowlist.json` without them → `allowlist reload` → ensure enforcement is on (D5) → `kick` → confirm. Not five controls the operator composes.

*Why:* the two obvious simplifications are both broken, and the spike proved it rather than assuming it. With `allow-list=false` — the shipped default, set deliberately by the installer so a fresh server is joinable — an allowlist edit excludes nobody at all. And with the player online, an allowlist edit plus reload leaves them standing in the world (verified: still in `online_players` afterwards). A "ban" that omits either step is a control that reports success and does nothing observable.

*Consequence:* ban is not available while the server is stopped, because its kick step is not. A stopped-server ban is offered as the durable half only, labelled as such, and the kick is unnecessary because nobody is connected.

### D3: A ban is a record cobble keeps, not an inference from the allowlist

`cobble.db` gains a ban table: xuid, the name as seen at ban time, reason, timestamp. Absence from `allowlist.json` is never read as evidence of a ban.

*Why:* everyone who has never joined is also absent from the allowlist. Without its own record cobble cannot tell exclusion from the default state, cannot show why or when, and unban has nothing to restore — it would have to guess whether to add a name that may never have been there. The record is also where the xuid↔name binding is pinned at the moment of the ban, which matters because the allowlist is name-keyed and names change.

*Consequence:* an existing installation with a populated allowlist and no ban history reports every entry as simply allowed. Nothing is back-filled; there is no source to back-fill from.

### D4: Cobble writes the xuid that BDS omits

An allowlist entry cobble creates for a player in its roster carries `xuid` alongside `name`. BDS never writes that field itself (verified, even for an online player), but the schema accepts it.

*Why:* a name-only entry stops matching its owner the moment they change their gamertag — silently unbanning a banned player, or locking out an allowed one. Cobble holds the stable xuid and the current name for everyone who has played here; writing both is the only way an entry survives a rename. This is the clearest instance of the general point that cobble's roster is the only join between these namespaces.

*Consequence:* an entry for someone who has never played carries no xuid, because cobble does not have one. Those entries remain name-only and rename-fragile, and are presented as such.

### D5: `allow-list` is written to both masters; live state is learned by observation

Saving `allow-list` writes `server.properties` **and** sends `allowlist on`/`off`. Cobble tracks the live enforcement state by parsing the two lines the server prints when it changes — `Turned on the allowlist` / `Turned off the allowlist` — as typed events, exactly as online players are tracked.

*Why:* `allowlist on` does not touch `server.properties` (verified), and M3's pending-vs-live panel compares the file against a spawn snapshot, never against the live server — so the divergence is structurally invisible to it, and reverts at the next restart with no warning. Worse, **there is no command to read the live state**: `allowlist list` returns members, not whether enforcement is on. Reading is impossible, so observing the transitions is the only way to know. The lines are ordinary console output already flowing through the M1 parser.

*Consequence:* this narrows the `server-config` guarantee that a saved setting is pending until restart — `allow-list` now applies immediately too. Drift is still possible for the interval before cobble first observes a transition (an operator who ran `allowlist on` in a previous cobble process, then restarted cobble but not the server), so the live state is asserted from the file at every server-ready rather than assumed. A ban that turns enforcement on does not turn it off again on unban: cobble does not know whether the operator has since come to rely on it, and silently reopening a server is a worse failure than leaving it closed.

### D6: A kick is confirmed by the disconnect, and its intent is registered before the send

Kick sends `kick <name> [reason]` through the **echoed** path and resolves when the roster observes `PLAYER_DISCONNECTED` for that xuid within a timeout. The intent — "a disconnect for this xuid in the next N seconds is a kick" — is registered before the command is sent.

*Why:* the acknowledgement is a single line and `Console.query` could match it, but the disconnect is ground truth rather than a claim about it, and it is already parsed, already typed, already consumed by the recorder. Registering intent beforehand is not optional: the disconnect line a kick produces is byte-identical to a voluntary leave (verified — `Player disconnected: <name>, xuid: …, pfid: …` in both cases), and it arrives ~5ms after the acknowledgement, so there is no window in which to decide afterwards. Without pre-registration a kicked session records as an ordinary disconnect and the reason is lost.

*Why echoed, not silent:* M5's D3 established a non-echoed path so a 39-value gamerule dump would not flood the operator's console. A kick is the opposite case — a consequential act against a person, worth seeing in the console precisely because it is auditable. Inheriting the silent path here would hide it by habit rather than by decision.

*Consequence:* a kick that produces no disconnect within the timeout is reported as unconfirmed rather than failed; the operator sees the console line and can judge. The `No targets matched selector` case is distinguishable and reported as such.

### D7: A silent write is confirmed by re-reading — the M5 doctrine, inherited

`permission set` produces **no output at all** on success (verified) — not an acknowledgement, not an error. Cobble writes `permissions.json` itself (D1), issues `permission reload`, and confirms by re-reading the file.

*Why:* this is the same failure shape M5 hit from a different direction, where `sendCommandFeedback false` suppressed the gamerule write acknowledgement. The doctrine that survived — never trust the reply, re-read and report what you read — transfers without modification. Here it is not even conditional on a setting: `permission set` is unconditionally silent.

### D8: `null` is empty

Every read of `allowlist.json` and `permissions.json` folds `null` to the empty list, and tolerates a file that is absent, empty, or unparseable by reporting the condition rather than raising.

*Why:* BDS writes **literal `null`** into `allowlist.json` when the last entry is removed (reproduced twice), not `[]`. A reader that does `json.load()` and iterates raises `TypeError` on the first unban of the last banned player — a crash on a rare path, which is the worst kind to ship. `allowlist list` reports the same state as `"result":null`, so this is consistent rather than a one-off.

*Consequence:* cobble always writes `[]` for an empty list. The `null` form is accepted on read and never produced.

### D9: Moderation file writes take the maintenance interlock; kick needs no guard

Writes to either file are refused with `MaintenanceInProgressError` while an update, backup, or restore is in progress, as configuration and gamerule writes already are. Kick takes no such guard.

*Why:* a file write racing a backup capture is exactly the hazard the interlock exists for. Kick needs nothing because every maintenance operation stops the server first (cold capture), so a kick during maintenance is already refused by `NotRunningError` on the path it shares with every other console command. Adding a second guard would be a redundant special case.

### D10: This change adds nothing to the console layer

No extension to `Console.query`, no multi-line reply reader, no correlation framework.

*Why:* worth stating explicitly, because three milestones deferred this work on the belief that it required exactly that. M5 built the layer and this change does not use it. The reply shapes that would have needed a multi-line reader — the `###*` envelopes, `permission reload`'s two lines — are only produced by commands D1 replaced with file reads. What moderation actually needed was the identity join, which is cobble's roster, and two lines added to the event parser.

## Risks / Trade-offs

**A first ban locks out more people than the target** → The single sharpest hazard here, and it is a UI problem, not a mechanical one. Turning enforcement on excludes everyone not on the allowlist, which on a default install is everyone. Cobble names them from the roster before the operator commits and offers to carry them onto the list in the same action. Stated as a requirement, not left to the frontend.

**BDS rewrites a file cobble is holding** → An operator typing `allowlist add` in the console section changes the file underneath cobble's in-memory view. Mitigated by re-reading before every write rather than caching, and by parsing the `Added`/`Removed` console lines so an out-of-band edit is observed. Last write wins; cobble never merges.

**The live enforcement state cannot be read, only observed** → D5. A transition that happened while cobble was not watching is invisible until the next server-ready assertion corrects it. Accepted: unlike M5's gamerules, there is no read command to fall back on, so this is a hard platform limit rather than a design choice.

**A name-only allowlist entry is rename-fragile** → D4 writes the xuid where cobble has one. For an entry created before this change, or for a player who has never joined, cobble has no xuid and the entry stays name-only. Presented as such rather than silently trusted.

**Moderation makes the absent authentication consequential** → Until now the worst an unauthenticated LAN visitor could do was restart a game server. This change lets them ban the household. `auth_guard` remains the designed seam and every new route depends on it, but this change is the one that turns "LAN-only is fine" from comfortable into a judgement call worth revisiting.

**Bedrock output drift** → The parsers are confined to one module and the formats are tabulated in Context with their verification. An unrecognised line degrades to "unconfirmed", never to a false success.

## Migration Plan

No migration. New tables in `cobble.db` are created on first use and are inside the backup set already. The two JSON files are adopted exactly as found: an existing allowlist becomes the starting state with every entry reported as allowed and none as banned, and existing name-only entries are left name-only rather than being retro-fitted with xuids cobble cannot verify belong to them. Rollback is removing the new routes and section; the files remain valid for BDS and for a hand-editing operator, since every write preserves unrecognised fields.

## Open Questions

- **Does `content-log-console-output-enabled=true` surface player chat in stdout?** BDS logs `Content logging to console is disabled. Enable it with content-log-console-output-enabled=true` at boot. If chat does appear, a later change could give cobble evidence of its own rather than relying entirely on the operator having been told. Deferring is safe: this change treats cobble as the instrument and never the detector, and nothing in the specs or the task breakdown changes if the answer turns out to be yes. Untested because it needs a restart plus a chatting client.
- **Does BDS preserve an `xuid` field cobble writes into `allowlist.json`?** The schema accepts it and D4 depends on it surviving. If BDS strips it on its own rewrite, D4 degrades to name-only with no other consequence — the entry still works, it is simply rename-fragile again. Verifiable in one probe during implementation.
