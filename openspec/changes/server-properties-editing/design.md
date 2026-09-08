## Context

See proposal.md — Why. The constraints that shape this design come from decisions already made in M1 and M2:

- **BDS reads `server.properties` exactly once, at spawn.** Nothing cobble writes affects a running server. Every design decision below follows from this.
- **`data/` is stable and cobble owns it.** M2 relocated `server.properties`, `allowlist.json`, `permissions.json` and `worlds/` into `/srv/bedrock/data/`, which a version swap never touches. The file cobble edits is at a fixed path with no version in it.
- **BDS is a direct child of the cobble process.** Cobble cannot outlive a BDS process or attach to one it did not spawn; restarting cobble restarts BDS. Any state describing "the currently running server" is therefore safe to hold in memory.
- **A maintenance interlock already exists.** `MaintenanceInProgressError` and the maintenance scope from M2 mediate access to the server and to `data/`; a restore replaces `data/` wholesale.
- **Commands are fire-and-forget.** Console input is relayed to stdin with no correlation of BDS's reply, and the event vocabulary has no command-output type. This is why M3 stops at `server.properties` and leaves gamerules and allowlist editing to a later milestone.

## Goals / Non-Goals

**Goals:**

- Editing `server.properties` from the browser is at least as safe as editing it over SSH, and considerably harder to get wrong.
- A save never disrupts players; applying is always an explicit, separate act.
- "Which settings are waiting on a restart" is derived from observed fact, not tracked with a flag that can desynchronise.
- A file that has been hand-edited, or that carries vendor comments, survives a save byte-for-byte apart from the lines actually changed.

**Non-Goals:**

- Any editing mechanism that requires reading a value back out of the running server. That needs console command/response, which does not exist yet.
- A whole-file raw text editor. Unknown keys are editable as key/value rows; offering a free-text pane as well would create a second write path with different validation, for a file the operator can still edit over SSH if they truly need to.
- Conflict detection between a browser save and a simultaneous hand-edit.
- Configuration history, undo, or revert (proposal.md — Deferred).

## Decisions

### D1: The file is modelled as an ordered line document, not a dictionary

`server.properties` is parsed into a sequence of lines, each classified as a comment, a blank, or a key/value assignment. Writing mutates the value of matched assignment lines in place and appends any genuinely new key at the end. Comments, blank lines, key order, duplicate keys, and keys cobble does not recognise all survive a write untouched.

*Why:* the obvious alternative — parse to a `dict`, write it back out — silently discards every comment in the vendor file and reorders the operator's keys, so the first save from the browser would produce a large, alarming diff for anyone watching the file over SSH. `_apply_install_defaults()` ([installer.py:239](src/cobble/acquisition/installer.py:239)) already edits this file line-in-place; this is the same discipline generalised, not a new pattern.

*Duplicate keys:* BDS takes the last assignment of a repeated key. Cobble reads the same way and writes to the last occurrence, leaving earlier ones as-is.

### D2: A static property schema, with unknown keys still editable

Cobble carries its own table of recognised properties — key, type (bool / int / enum / string), documented default, valid range or member set, and a short description. Keys in the file that are not in the table are presented as plain editable text rows.

*Why:* the schema is what turns a text field into a checkbox, a bounded number, or a dropdown, and it is what lets cobble explain what a setting does. Deriving it from the file instead is impossible — `server.properties` carries no type information. Making the schema authoritative over the file, however, would mean a BDS release that adds a property renders it uneditable until cobble ships a new schema. Unknown-keys-as-text removes that coupling: the schema improves the experience for keys cobble knows, and never gates the ones it does not.

*Alternative rejected:* a curated allowlist that hides unrecognised keys. It makes cobble strictly less capable than `nano` for no safety gain, since none of these keys are destructive (D4).

### D3: Validation rejects type errors, permits out-of-range values with a warning

A write is rejected, per-key, when a value cannot be the declared type — a non-integer in an integer field, a value outside an enum's member set, a non-boolean in a boolean field. A value that parses correctly but falls outside cobble's recorded range is accepted, with a warning surfaced alongside it.

*Why:* type errors are unambiguously wrong and BDS's own handling of them is inconsistent (some fall back to a default silently, which is worse than a rejection). Ranges are cobble's belief about what is sensible, and that belief will sometimes be out of date or simply narrower than what an operator wants on their own hardware. Hard-failing on a range would make cobble's stale table an obstacle. Validation is enforced server-side; the browser mirrors it for immediate feedback but is not trusted.

### D4: `level-name` is a selection over existing worlds, not a text field

Cobble enumerates the directories under `data/worlds/` and presents `level-name` as a choice among them, with "create a new world" a separately labelled action that takes a name.

*Why:* this is the only key in the file whose effect is routinely misread. It selects which world BDS loads; a name with no matching directory causes BDS to create a fresh empty one, which from inside the game is indistinguishable from the world having been wiped. It is fully reversible — the previous directory is untouched, and backups capture `worlds/` wholesale rather than only the active level ([service.py:439](src/cobble/backup/service.py:439)) — so the problem is alarm and confusion, not data loss. A picker makes the reversible-but-surprising thing obvious and makes the intentional thing (a genuinely new world) explicit.

*Note:* this is the one place the interface deliberately does not mirror the file's shape. Because the underlying key is still a string, the raw value remains visible.

### D5: The configuration in effect is snapshotted at spawn, in memory

When the supervisor spawns BDS it captures the effective key/value map of `server.properties` as it stood at that moment and holds it for the life of that process. Pending changes are computed by comparing the file on disk against that snapshot.

*Why:* this makes "3 settings are waiting on a restart" a derived fact rather than a dirty flag. A flag has to be set on every write path and cleared on every start path, and desynchronises the moment anything edits the file outside cobble — which, over SSH, is exactly what will happen. A snapshot is correct regardless of who wrote the file or how.

Memory is sufficient storage because BDS cannot outlive the cobble process that spawned it; there is no "cobble restarted while the server kept running" case to persist across. If that ever changes — the M1 design notes a possible future split of cobble from BDS — the snapshot becomes the thing that must be persisted, and this is the only place that assumption is relied upon.

*Comparison is over effective values:* the parsed last-assignment-wins map on both sides, so a comment or reordering edit produces no pending changes.

### D6: Applying is an ordinary restart, not a maintenance operation

The interface offers a restart after a successful save; the operator may take it or defer. Taking it calls the existing `Supervisor.restart()` with its M1 clean-shutdown guarantees. Deferring leaves the change pending, and it applies at the next start from any cause — an operator start, a crash restart, or an M2 update.

*Why:* a maintenance scope exists to serialize multi-step operations that own the server across several run-state transitions and need a rollback story. Applying configuration is a single restart with no intermediate state to protect and nothing to roll back. Wrapping it in a scope would add a fourth maintenance operation to the status model and to every interlock check, in exchange for nothing.

*Consequence worth stating:* a deferred change becomes live at the next start whatever triggers it, including an unattended 04:00 update. An operator who saves and defers has, in effect, scheduled the change. The interface says so rather than implying the change is inert until they personally restart.

### D7: Writes are refused during maintenance, and are atomic

A write attempted while a maintenance operation is in progress fails with the existing maintenance error. Writes go to a temporary file in `data/` and are renamed into place.

*Why:* an M2 restore replaces `data/` wholesale, so a write racing it could be silently discarded or could land on top of restored state. Refusing is the right shape rather than queuing, because a configuration write is instantaneous and an operator can simply retry in a few seconds; queuing would mean a save that appears to succeed and takes effect at an unpredictable later moment. Rename-into-place ensures BDS or a backup never observes a half-written file.

## Risks / Trade-offs

**A BDS release renames or removes a property cobble's schema knows** → the key survives in the file as an unknown key and stays editable (D2); the schema entry becomes dead and is removed when noticed. No operator-visible breakage, and no release coupling.

**Cobble's recorded range for a property is wrong or stale** → out-of-range values are permitted with a warning (D3), so a stale table degrades to noise rather than an obstacle.

**An operator saves, defers the restart, and forgets** → the change applies at the next start from any cause, possibly unattended (D6). Mitigated by keeping the pending state visible in status rather than only in a transient prompt, so it is present whenever the interface is opened.

**A hand-edit over SSH is overwritten by a browser save in flight** → last write wins and the hand-edit is lost. Accepted deliberately: the failure mode is a lost edit, not a corrupted file, and the window is seconds wide on a single-operator LAN tool. Detection machinery is not worth its complexity here.

**`level-name` is pointed at a world directory that is later removed outside cobble** → the picker no longer lists it while the file still names it. The current value is shown regardless, marked as missing, so the discrepancy is visible rather than the value silently disappearing from the interface.

**The in-memory snapshot assumption is invalidated by a future cobble/BDS process split** → pending-vs-live would report nonsense after a cobble restart. Confined to one place by design (D5) and called out there.

## Migration Plan

No migration. This change introduces no durable state, no new files, and no layout change: it reads and writes a file that M2 already placed at a stable path and already captures in backups. Deploying is an ordinary release; rolling back to the prior release leaves `server.properties` valid and readable, since every write produces a normal properties file.
