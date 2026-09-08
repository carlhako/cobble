## Why

M1 supervises the server and M2 keeps it current and recoverable, but the only way to change how the server actually plays — difficulty, player cap, view distance, the message players see in their server list — is still to SSH into the container and edit `server.properties` by hand. That is exactly the workflow cobble exists to replace, and it is the last routine operator task that still requires a shell.

This is milestone **M3**, scoped deliberately to `server.properties` alone. Gamerule editing and the player roster both need a console command/response layer that does not exist yet (commands are relayed to stdin fire-and-forget, and there is no `COMMAND_OUTPUT` event type), so they are left to later milestones rather than dragged in here. `server.properties` needs none of it: the file lives in the stable `data/` directory M2 established, and BDS reads it at spawn.

## What Changes

- **A configuration screen for `server.properties`.** The whole file is presented — recognised keys as typed, validated inputs with their documented defaults and ranges; unrecognised keys as plain key/value rows. Nothing is hidden from the operator.
- **Saving is always safe; applying is a separate, deliberate act.** BDS reads `server.properties` once, at spawn, so a save alone never affects the running server. Cobble writes the file, then reports that saved settings differ from the running ones and offers a restart. The operator may restart immediately or defer — a deferred change stays pending and applies at the next start, whatever causes it.
- **Pending-vs-live is an observable fact, not a guess.** Cobble snapshots `server.properties` when it spawns BDS and compares the saved file against that snapshot, so status can report exactly which settings are waiting on a restart rather than inferring drift from a dirty flag.
- **`level-name` becomes a world picker.** The single genuinely confusing key in the file selects *which* world under `data/worlds/` BDS loads; typing a name with no matching directory creates a new empty world and reads, from inside the game, as though the world was wiped. Cobble enumerates the existing world directories and presents them as a choice, with creating a new world an explicit, separately-labelled action. Non-destructive either way — the other worlds stay on disk and in backups — but no longer a surprise.
- **Writes preserve the file.** Cobble rewrites only the lines it owns, leaving comment lines, key order, and any key it does not recognise untouched, so a hand-edited or vendor-commented file survives a save intact.
- **Writes refuse during maintenance.** An update or restore owns `data/`; a configuration write while one is in progress is rejected with the existing maintenance error rather than racing it.

Not breaking: all additions are new routes and a new UI section; no existing route changes shape, and the on-disk layout is unchanged from M2.

## Capabilities

### New Capabilities

- `server-config`: Reading, validating, and writing `server.properties` as operator-editable configuration — the property schema (types, defaults, ranges, and which keys cobble recognises), comment- and order-preserving writes, enumeration of the available worlds backing `level-name`, the snapshot of what the running server was started with, and the pending-versus-live comparison derived from it.

### Modified Capabilities

- `server-status`: Reports whether saved configuration differs from the configuration the running server was started with, and which settings are pending, so the interface can surface a restart-to-apply state without polling the file itself.
- `server-lifecycle`: A start or restart is the point at which pending configuration becomes live, and the run-state model gains the configuration snapshot taken at spawn. Configuration writes are refused while a maintenance operation holds the server, using the existing maintenance interlock.
- `web-ui-shell`: The interface gains a Configuration section presenting the property set, validation feedback, the world picker for `level-name`, and the pending-changes state with its restart prompt.

## Impact

**New code** — a `server.properties` parse/serialize module that round-trips comments and unknown keys, a property schema describing the recognised keys, a configuration service owning validation and the write path, the API routes exposing it, and the React configuration section.

**Modified code** — the supervisor (capture the configuration snapshot at spawn; expose it alongside the existing run state), the status tracker (a configuration view in `StatusSnapshot`, following the existing per-domain view pattern), and the web shell's section registry.

**Unchanged** — the on-disk layout, the backup format, and the update state machine. `server.properties` is already captured by backups and already relocated into `data/` by M2; M3 adds no new durable state and no new backup content.

**External dependencies** — none. No new services, no new packages.

**Deferred** — gamerule editing and the console command/response layer it requires, the player roster and moderation, and `allowlist.json` / `permissions.json` editing (all of which want the same command/response layer to confirm `allowlist reload` and friends). Configuration change history and undo are explicitly out of scope; backups already capture `server.properties`, and a dedicated revert can be added later without changing anything established here.
