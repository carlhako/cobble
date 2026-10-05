# Design

## Context

See proposal.md (Why) and `specs/server-identity/spec.md`. The facts that shape the approach:

- BDS runs with `data/` as its working directory (`Layout.data_dir`), so the key it reads and writes is `data/keys/server_identity_key.pem`.
- The `serveridentity` command (BDS 1.26.52.3) has three subcommands: `status`, `save` and `delete`. The replies, taken from the binary's strings and confirmed live for `status` on cobble-3:
  - `A saved server identity key exists at <path>.`
  - `No saved server identity key exists at <path>.`
  - `Saved server identity key to <path>.`
  - `Failed to save server identity key to <path>.`
  - The binary also has `Unable to replace server identity key file '%s'.`, so `save` may overwrite an existing file. cobble must not rely on BDS to refuse that.
- `Console.query(command, matcher, reply_timeout=…)` already sends a command on cobble's own behalf without echoing it, and keeps the matched reply away from clients. The gamerules service uses it.
- Services react to readiness by subscribing to the event bus and spawning a task on `EventType.SERVER_READY`. `AccessService._on_ready` is the pattern: wait for `RunState.RUNNING`, then act.
- `MUTABLE_ENTRIES` in `acquisition/layout.py` names the `data/` entries that are real state. Every other top-level entry of a version is treated as vendor payload and symlinked. `keys/` is not in the vendor tree today, and an unknown real directory in `data/` is left alone.
- Backups tar the whole of `data/`, and a restore replaces `data/` wholesale (`_replace_dir_contents`).
- The network view is built by `ConfigService.network()` → `network_view()` (`config/network.py`). It's served at `GET /api/config/network` and rendered by `web/src/sections/Network.tsx`.

## Goals / Non-Goals

**Goals:**
- One small service owns the identity: reading the state, saving once at readiness, and saving on request.
- Reading the state never touches the server.

**Non-Goals:**
- Generating, rotating, importing or deleting keys from cobble. `serveridentity delete` is not exposed.
- Showing a key fingerprint, or detecting that the running identity differs from the file. That happens only when someone places a key by hand while the server runs.
- A setting to turn the automatic save off.
- Fixing remote-join failures that have other causes (port forwarding, `online-mode`).

## Decisions

### D1. Save the running identity at readiness instead of generating a key before start

On `SERVER_READY`, if the key file is absent, cobble issues `serveridentity save` through `Console.query`, with a matcher for `Saved server identity key to` or `Failed to save server identity key to`.

- *Alternative*: generate a P-384 PEM before BDS starts (openssl or `cryptography`). Rejected. On an existing install it changes the identity one more time, which is the very thing that breaks trusted clients. It also adds a crypto dependency and a key-format contract that BDS already handles.
- *Alternative*: use `serveridentity status` to decide. Rejected. The file check is enough and needs no server round-trip, and the view needs the same check while the server is stopped anyway.

The file check happens immediately before the command, while holding the service's own lock (D3). This narrows the window in which an operator could drop a key in between. The rest of the risk is accepted (see Risks).

### D2. An `IdentityService` beside the other server services

`src/cobble/identity/service.py` holds:

- `state() -> IdentityState`: `saved` (file exists) and `running` (supervisor state). It's a pure read and never raises.
- `save_running() -> IdentityState`:
  - Raises `NotRunningError` when the server isn't running, and `MaintenanceInProgressError` during maintenance.
  - Returns without issuing anything when the file exists.
  - Raises `IdentitySaveError(reason)` on a `Failed …` reply or a timeout.
  - After a `Saved …` reply, cobble confirms that the file exists before reporting it saved.
- `on_event(event)`: spawns the readiness save. A failure is only logged.

The runtime wires it in the way `AccessService` is wired: construct it, then subscribe `on_event` to the bus. `ConfigService.network()` gains an `identity` argument, which the API layer passes in from `runtime.identity.state()`. That keeps `ConfigService` free of a supervisor dependency.

- *Alternative*: put it inside `ConfigService`. Rejected. The identity isn't a `server.properties` setting and needs the console.

### D3. Serialise the two save paths

The readiness save and a manual save can overlap: an operator clicks the button just after the server starts. Both go through one `asyncio.Lock` inside the service, and both re-check the file once they hold it. The second caller then sees the file and returns `saved` without issuing a command.

### D4. View and API shape

The network view gains a top-level `identity` key: `{"saved": bool, "running": bool}`. It's top-level rather than per layout because it isn't tied to a transport. The interface shows it only in the NetherNet layout (spec).

`POST /api/config/network/identity/save` runs `save_running()` and returns `{"identity": {...}}`. Errors map the same way as other server writes:
- not running → 409
- maintenance → 409, with the maintenance error body
- `IdentitySaveError` → 502, with the server's reason

It sits under `/api/config/network` because the Network section is its only caller.

### D5. Reserve `keys` as mutable state

Add `"keys"` to `MUTABLE_ENTRIES`, so a future BDS that ships a `keys/` directory in its vendor tree is never symlinked over the operator's key. Bootstrap seeding copies only files (`src.is_file()`), so `keys/` is never seeded. Exclude it from `_SEED_FILES` explicitly, as is already done for `worlds`, so the intent is clear.

### D6. File mode

After a successful save, cobble tightens `data/keys/` to `0700` and the PEM to `0600` if they are looser. BDS runs as the same `cobble` user, so it can still read them. The key also ends up in backup archives, which can be downloaded. The README's backup section says so.

### D7. Network section

`Network.tsx` renders a "Server identity" row in the NetherNet layout from `identity`:
- **Saved**: shown as "Saved".
- **Not saved, running**: "Not saved: changes on every restart", the explanation, and a "Save current identity" button. The button is hidden during maintenance, using the existing maintenance hook.
- **Not saved, stopped**: "Will be saved at the next start".

On success the section replaces `identity` from the response. On failure it shows the reason inline. The row is independent of the settings draft, so saving it never submits configuration.

## Risks / Trade-offs

- **The reply strings may change in a later BDS.** The matcher then times out, the save is logged as failed, and the view still reports from the file. If BDS did save despite the timeout, the next read reports it as saved. So the visible effect of a reply-format change is only a stray warning in the log.
- **`save` can overwrite a key placed by hand in the moment between cobble's file check and the command.** This needs a person to place a key during the second after startup. It's accepted, and the D3 lock re-check narrows it further.
- **A backup restored from before the key existed changes the identity once.** That's inherent: the key isn't in that backup. The next readiness saves the new identity, so it happens only once.
- **Restoring another instance's backup brings that instance's identity.** That's the intended behaviour when moving a server, and it's documented.
- **A private key inside downloadable backups.** It's documented, and the file mode is tightened on disk. Anyone who can download backups already holds the whole world.

## Migration Plan

Nothing to migrate. On the first start after upgrading, an install without a key saves its running identity. Clients that trusted that run's identity keep working, and from then on the identity is stable. Rolling back to an older cobble leaves `data/keys/` in place, and BDS keeps using it.
