## Context

See proposal.md — Why. This design rests on a spike run against BDS **1.26.45.1** on the live host, which retired the assumption three earlier milestones were built on ("commands are fire-and-forget… this is why M3 stops at `server.properties` and leaves gamerules and allowlist editing to a later milestone" — M3 design.md). The observed facts, all of which the design below depends on:

| Probe | Result |
|---|---|
| `gamerule` (no argument) | **One line**, all 39 rules: `commandBlockOutput = true, doDayLightCycle = true, …` — canonical camelCase names, comma-separated |
| `gamerule mobgriefing` | `mobgriefing = true` — echoes the caller's casing, not the canonical name |
| `gamerule mobgriefing false` | `Game rule mobgriefing has been updated to false` |
| bad value | `Syntax error: Unexpected "bananas": at "bgriefing >>bananas<<"` |
| unknown rule | `Syntax error: Unexpected "notarealrule": at "/gamerule >>notarealrule<<"` |
| out of range | `The number you have entered (99999) is too big, it must be at most 4096` |
| unknown command | `Unknown command: cobble-sync-7f3a1c. …` — **echoes the input verbatim** |
| `sendcommandfeedback false`, then a write | **no output at all**; a *query* still replies normally |
| gamerule change, then 16 min running | `level.dat` untouched — mtime and md5 unchanged |
| gamerule change, then clean restart | `level.dat` rewritten (3602 → 3612 bytes); **the changed value survived** |

Rule shapes on 1.26.45.1: 33 booleans, 5 bounded integers (`randomTickSpeed` ≤ 4096, `maxCommandChainLength`, `functionCommandLimit`, `spawnRadius`, `playersSleepingPercentage`), 1 enum (`playerWaypoints`). Rule names and values are case-insensitive on input.

Constraints inherited from earlier milestones:

- **BDS is a direct child of cobble** and cobble owns its stdin. Every gamerule read or write is a console exchange; there is no other channel.
- **`Console.submit_command` echoes unconditionally** — `self._buffer.add_command(command)` is a specified guarantee, not an implementation detail.
- **A maintenance interlock exists** (`MaintenanceInProgressError`); a restore replaces `data/` wholesale.
- **`cobble.db` exists** (M4) and is inside the backup set, with a checkpoint before capture.
- **Supervisor hooks exist** for server-ready and pre-stop; the player recorder already uses both.

## Goals / Non-Goals

**Goals:**

- Toggling a gamerule from the browser is immediate, needs no restart, and is confirmed by a value read back from the server rather than by trusting an acknowledgement.
- Cobble's picture of a world's rules survives the things that lose them — a restore, a new world, a world switch — without cobble ever overruling a person who deliberately changed one.
- Everything cobble does to a gamerule on the operator's behalf is visible after the fact. No silent writes.
- The Bedrock output formats this depends on are confined to one module and one reply shape, so a version that changes them fails in a diagnosable place.

**Non-Goals:**

- A general console request/response layer. The bulk dump makes this a one-shot exchange; building a correlation framework for a single caller would be speculative. `kick` and `allowlist add` can justify their own when they arrive.
- Reading gamerules from `level.dat`. See D7.
- Enforcement — holding a rule against an operator who changed it in game. Considered and rejected; see D5.
- Any history of gamerule changes beyond the current record and the unacknowledged report. Backups already capture the world.

## Decisions

### D1: One query shape — cobble never reads a single rule

Cobble issues exactly two forms: `gamerule` to read everything, and `gamerule <name> <value>` to write. A single-rule read is never issued, including after a write — a write is followed by a full bulk read.

*Why:* one parser, one reply shape, one timeout, one set of failure modes. The single-rule reply also echoes the caller's casing (`mobgriefing = true`, not `mobGriefing`), so it is a worse source of canonical names than the bulk dump, which supplies them for free. Reading 39 values to confirm one write costs a single line of output.

*Alternative rejected:* per-rule reads to minimise output. The output is suppressed from the console anyway (D3), so there is nothing to minimise.

### D2: The write acknowledgement is never parsed

A write is `gamerule <name> <value>` followed by a bulk read; the outcome is whatever the read reports. The acknowledgement line is discarded.

*Why:* `sendCommandFeedback` is itself one of the 39 rules and is editable from this very section. With it false, a write produces **no output at all** (verified) while queries continue to reply normally. Any design that parses the acknowledgement breaks the moment an operator toggles that rule — and breaks in the worst way, by reporting failure for writes that succeeded. Re-reading is correct under both values with no special case.

*Consequence:* an operator setting `sendCommandFeedback` false is fully supported and needs no warning.

### D3: A separate, non-echoed submission path on the console

`Console` gains a second entry point for commands cobble originates. It shares the existing `_command_lock` and the running-state check with `submit_command`, but does not call `_buffer.add_command`, and it registers a one-shot matcher that consumes the reply line before fan-out.

*Why:* a bulk read emits a 39-value line. Sampling at start, before every stop, and while the section is open would bury the operator's console in noise that is meaningless to them. The API router never exposes this path, so the narrowed echo guarantee applies only to cobble's own traffic.

*Reply capture:* the matcher takes the first line, within a bounded timeout, that has the bulk-dump shape — an `INFO` line containing at least several ` = ` pairs separated by `, `. Content logging to console is disabled by default on BDS, so player chat cannot reach stdout and imitate it.

*Alternative held in reserve:* the sentinel bracket — follow the real command with a deliberately invalid one carrying a nonce, and read until the `Unknown command: <nonce>` line, which echoes the input verbatim (verified working). It bounds the response without knowing its format at all, and is the escalation path if a future BDS changes the dump's shape. It is not used now because it doubles the commands sent and the shape match is unambiguous today.

*Timeout:* a query that produces no matching line is abandoned and reported failed. The console and the server are untouched either way — nothing about this path can block the stdout pump, which the event bus already guarantees.

### D4: Sampling at start, before stop, and while the section is open

The record is refreshed when the server signals readiness, opportunistically just before cobble stops it, and on a poll while a client has the gamerules section open. There is no unconditional background poll.

*Why:* the start sample is the one that matters — it is where adoption, repair, and defaults are decided. The pre-stop sample only improves what the section shows while stopped, so it is strictly best-effort: the server is about to go away, and a sample that does not complete simply leaves the previous one standing. The open-section poll gives near-live drift detection to someone actually looking, at zero cost when nobody is.

*Alternative rejected:* an unconditional poll every N seconds. It buys drift detection nobody is waiting on and puts a permanent command on the server's input channel.

### D5: Divergence is adopted, not enforced

When the live set differs from the record and cobble did not cause it, cobble records the live value and reports that it did. It does not put the old value back.

*Why:* only an operator can change a gamerule in game, so a divergence is a deliberate act by someone entitled to perform it. Enforcement inverts that — cobble would silently revert a person's change at the next restart, producing the least diagnosable class of bug there is ("the server keeps undoing my setting"). Adoption keeps cobble's record true and keeps the operator informed, which is what the record is for.

*Consequence:* the record is descriptive, not prescriptive. Its purpose is to restore rules that were **lost**, not to prevent rules from being **changed**.

### D6: A restore marks the next start as a repair

The restore path writes a marker naming the world it restored. The first readiness after that marker consumes it and, on a divergence, re-applies the recorded values instead of adopting them.

*Why:* a restore reverts the world's gamerules along with everything else, and by value alone that is indistinguishable from an in-game change — same observation, opposite correct response. The disambiguation is not in the data; it is in cobble's knowledge that it just performed the restore. Cobble performs every restore, so the marker is always available.

*Marker lifetime:* consumed by the first readiness after it is set, whether or not a divergence is found, so it can never leak into a later start. If cobble is killed between the restore and the next start, the marker survives in `cobble.db` and is consumed on the following start — the desired behaviour.

*Reported either way:* a repair names every rule it re-applied. A restore that silently re-imposed old gamerules would be the same trap as enforcement.

### D7: No world-file parsing

Gamerules are read only from a running server. A stopped world shows its last record; a world cobble has never run reports that its rules have not been read.

*Why:* the spike confirmed `level.dat` is uncompressed little-endian NBT with gamerules as lowercased root keys, so parsing it is genuinely feasible — around 100–150 lines. It was rejected anyway, because it buys almost nothing. It is written **only on clean shutdown** (16 minutes of running left it byte-identical), so it is never a live source, and the pre-stop sample already covers the stopped case exactly. The single case it would serve is a world cobble has never started — where "not yet read" is an honest and adequate answer. A hand-rolled binary parser for a vendor format, run against files an operator can replace from a backup, is a poor trade for that.

*Reconsider if:* the world picker grows a need to preview a world's rules before switching to it.

### D8: Per-world record keyed by level-name, plus a defaults tier

Records live in `cobble.db`, keyed by the world's name as it appears in `level-name`. A separate, world-independent table holds the operator's preferred defaults, applied once when a world is observed for the first time.

*Why per-world:* gamerules are a property of the world, not the server. The host already carries two worlds with independent rule sets, and M3's world picker makes switching a normal action.

*Why a defaults tier at all:* per-world memory by construction cannot carry a preference into a world that did not exist when the preference was set. Creating a world would silently reset every rule to vendor defaults, which is exactly the loss the record exists to prevent.

*Keying on level-name:* a world renamed on disk is a world cobble has not seen, so it takes the defaults and starts a fresh record. Acceptable — renaming a world is rare and deliberate — and the alternative, a world identity derived from world-file contents, would need D7's parser back.

### D9: The rule catalogue is discovered, the type table is static

The set of rules is whatever the server's dump reports. A static table supplies each known rule's type, range, and description; a rule absent from the table is carried through with its raw value and marked unrecognised.

*Why:* the same discipline as M3's property schema — the table is an aid to presentation, never authoritative over what the server says. A BDS release that adds a gamerule surfaces it as an editable text row rather than hiding it, and cobble needs no update to keep showing the truth. Cobble also pre-validates against the table to give an immediate, specific error, but the server validates again and its refusals are surfaced verbatim.

## Risks / Trade-offs

- **Bedrock changes the dump format** → the shape matcher fails, the query times out, and the section reports that the rules could not be read rather than showing wrong values. All parsing sits in one module with the verified formats recorded above; the sentinel bracket (D3) is the tested escalation.
- **A rule is changed in game during the window between a write and its confirming read** → the read reports the other value, and the operator sees the true state rather than what they submitted. Acceptable: the displayed value is always the value in effect.
- **Adoption records a change the operator did not intend** (a guest with op rights) → adoption is always reported, naming the rule and value, and the operator can change it back in one click. This is the deliberate trade against silent enforcement.
- **The pre-stop sample does not complete** → the previous sample stands and the stopped view is slightly stale, marked with the time it was taken. The start sample makes it correct again.
- **The reply matcher consumes a line that was not the reply** → possible only for an `INFO` line carrying several ` = ` pairs while a query is outstanding. Content logging to console is off by default, so player-authored text cannot reach stdout. The consumed line is logged so a false match is diagnosable.
- **`level-name` changes while the server runs** → it cannot; M3 established that BDS reads `server.properties` only at spawn, so the active world is fixed for the lifetime of a process.
- **Defaults are applied to a world the operator did not mean to create** → the application is reported like any other, naming the world and every rule set.

## Migration Plan

No migration. New tables are created in `cobble.db` on first run alongside M4's; the existing checkpoint-before-capture covers them without change. A world with no record acquires one at the next readiness — with the operator's defaults if any are set, otherwise by recording what is already there. Nothing in the existing installation is read, moved, or rewritten.

Rollback is removing the release: the tables are additive and ignored by an earlier version, and no gamerule is changed on the server except by an explicit operator action, a repair after a restore, or the first-sight application of defaults — all of which are reported when they happen.
