## Why

Gamerules are the settings a family server actually reaches for — keep inventory on for an evening, turn mob griefing off, stop the weather cycle — and cobble cannot touch them. They live in the world, not in `server.properties`, so M3's configuration editor does not reach them. The only way to change one today is to be in-game with operator rights, or to type into the console section by hand and know the syntax.

Every milestone since M1 has deferred this for the same stated reason: gamerules were believed to require a general console command/response layer that does not exist ("commands are fire-and-forget… this is why M3 stops at `server.properties`", M3 design.md). **A spike against BDS 1.26.45.1 on the live host has retired that assumption.** The `gamerule` command with no arguments returns every rule and its value on a single line, so reading the full state is one command and one reply — a trivially bounded exchange, not a correlation problem. There is nothing general to build, and no reason to keep waiting.

The spike also established that a value changed in-game is invisible to cobble, that a backup restore silently reverts gamerules along with the world, and that a new world resets all of them to vendor defaults. So an editor alone would be a lie the moment anything else touched the world. This change makes cobble remember, per world, what the rules are — and say so when they move.

## What Changes

- **Live gamerule editing.** A Gamerules section lists every rule the running server reports, typed (33 booleans, 5 bounded integers, 1 enum on 1.26.45.1) and grouped. Changing one applies immediately: BDS accepts `gamerule` against a running server with no restart and no world reload.
- **Writes are confirmed by re-reading, never by parsing the reply.** `sendCommandFeedback` is itself a gamerule, and setting it false suppresses the "Game rule X has been updated" confirmation while leaving query output intact (verified). A write is therefore followed by a fresh read, which is correct under either value.
- **A silent internal command path.** Cobble needs to ask the server for gamerules without the request and its 39-value reply appearing in the operator's console. `Console.submit_command` currently echoes every command to every client by specification; this adds a separate, non-echoed path reserved for cobble's own queries. **BREAKING** to the `server-console` requirement that command input is echoed — the guarantee is narrowed to operator-submitted commands.
- **A per-world record of the rules.** Keyed by `level-name` and stored in the existing `cobble.db`, sampled when the server becomes ready and again immediately before cobble stops it. This record is what the section shows while the server is stopped, so the stopped case needs no world-file parsing.
- **Drift is adopted, not reverted.** If the live rules differ from the record and cobble did not cause it, the in-game change is legitimate: cobble records the new value and reports that it did. Cobble never silently puts a rule back that an operator deliberately changed.
- **Except after a restore, where drift is repaired.** A restore reverts the world's rules along with everything else, and is indistinguishable from an in-game change by value alone. Cobble knows it performed the restore, and on the next start re-applies the record instead of adopting it — reporting that too.
- **New-world defaults.** A set of rules the operator marks as their preference, applied once to any world cobble sees for the first time. Per-world memory cannot carry a preference into a world that did not exist yet; this is the tier that does.

Not included: enforcement. Cobble never holds a rule against an operator who changes it in-game — that behaviour was considered and rejected as a silent-surprise generator. No world-file (NBT) parsing: a world cobble has never run reports its rules as not yet read rather than being parsed cold. No moderation actions, no `allowlist.json` / `permissions.json` editing, and no general command/response layer — should `kick` or `allowlist add` later need reply correlation, they can build it then, on evidence of their own.

## Capabilities

### New Capabilities
- `server-gamerules`: What a gamerule is to cobble — how the live set is read and written, how a per-world record is sampled and kept, how a divergence between them is classified as adoption or repair and reported, and how defaults are applied to a world seen for the first time.

### Modified Capabilities
- `server-console`: The echo guarantee is narrowed. Command input is echoed to clients when an operator submits it; cobble's own internal queries are relayed to the server without appearing in the console stream.
- `server-status`: Gamerule activity is reported — whether the live set has been read, and any adoption or repair cobble performed that the operator has not yet seen.
- `web-ui-shell`: Adds the Gamerules section — the typed rule list, immediate application, the stopped-server presentation, the defaults editor, and the surfacing of an adoption or repair.

## Impact

**New code** — a `cobble/gamerules/` package owning the rule catalogue and its types, the line parser for both the bulk dump and the single-rule reply, the per-world store, and the service that samples, classifies drift, and applies defaults; an API router at `/api/gamerules`; a `Gamerules.tsx` section in the frontend.

**Modified code** — `cobble/console/console.py` (the silent submission path); `cobble/runtime.py` (wire the service to server-ready and pre-stop, as the player recorder already is); `cobble/status/tracker.py` (the gamerules block); `cobble/backup/service.py` (mark a restore so the next start repairs rather than adopts); `web/src/sections.tsx` (register the section).

**Dependencies** — none added.

**Data** — new tables in the existing `<state_dir>/cobble.db`. Already inside the backup set; the checkpoint M4 added before capture covers them unchanged. Nothing is migrated: a world's record begins at the first sample, and a world with no record reports as not yet read rather than guessing.

**Bedrock coupling** — this change parses BDS console output, which is undocumented and free to drift between versions. The parser is confined to one module, the rule catalogue is derived from what the server reports rather than hardcoded, and an unrecognised rule name is surfaced rather than dropped. The formats relied on are recorded with their verification in design.md.

**Unaffected** — the supervisor's process model, the event vocabulary and bus, `server.properties` editing, the update and backup state machines, and the authentication posture (`auth_guard` remains the no-op seam; the write routes depend on it as the other state-changing routers do).
