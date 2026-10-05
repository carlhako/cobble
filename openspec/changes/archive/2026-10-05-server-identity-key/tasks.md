# Tasks

Builds on `network-settings`. Apply that change first, or apply this one on top of its branch.

## 1. Layout (backend)

- [x] 1.1 Add `"keys"` to `MUTABLE_ENTRIES` and exclude it from bootstrap's `_SEED_FILES` alongside `worlds` (design D5). Verify in `tests/acquisition/test_layout_and_install.py`:
  - a vendor tree that contains a `keys/` directory gets no `data/keys` symlink;
  - an existing `data/keys/server_identity_key.pem` survives `set_active_version` plus `ensure_payload_symlinks` byte for byte;
  - a fresh bootstrap does not create `data/keys`.

## 2. Identity service (backend)

- [x] 2.1 Create `src/cobble/identity/service.py` with `IdentityState(saved, running)`, `IdentityService.state()`, and the reply matchers for `Saved server identity key to` and `Failed to save server identity key to` (design D1, D2). Verify with unit tests in `tests/identity/test_service.py`:
  - `state()` reports `saved` from the file alone, with the server stopped and with it running;
  - the matchers accept the real reply lines (with the BDS log prefix) and reject `A saved server identity key exists at …`.
- [x] 2.2 Implement `save_running()` with the lock and the re-check under it (design D3), the file confirmation, and the mode tightening to `0700`/`0600` (design D6). Verify with a fake console:
  - it issues `serveridentity save` through `query` (never `submit_command`) when the file is absent;
  - it issues nothing when the file exists;
  - it raises `NotRunningError` when stopped and `MaintenanceInProgressError` during maintenance;
  - a `Failed …` reply raises `IdentitySaveError` carrying the reply;
  - a timeout raises `IdentitySaveError`;
  - two concurrent calls issue exactly one command;
  - a looser existing mode is tightened after a save.
- [x] 2.3 Add `on_event()`, which on `SERVER_READY` waits for `RUNNING` and calls `save_running()`, logging any failure (the `AccessService._on_ready` pattern). Wire it into `runtime.py` and subscribe it to the bus. Verify:
  - readiness with no key issues one save;
  - readiness with a key issues none;
  - a failure is logged and leaves the supervisor state unchanged.

## 3. Network view and API (backend)

- [x] 3.1 Pass the identity state into the network view as a top-level `identity: {saved, running}` (design D4), keeping `ConfigService` free of the supervisor. Verify in `tests/config/test_network.py` and `tests/api/test_config.py` that `GET /api/config/network` carries `identity` for a running server with no key, a running server with a key, and a stopped server.
- [x] 3.2 Add `POST /api/config/network/identity/save`, mapping not running to 409, maintenance to 409 with the maintenance error body, and `IdentitySaveError` to 502 with the reason. Verify in `tests/api/test_config.py`:
  - success returns `identity.saved: true`;
  - each error maps to its status;
  - a request with the key already present returns saved without a console command.

## 4. Network section (frontend)

- [x] 4.1 Add the `identity` field to `NetworkView` and add `saveIdentity()` in `web/src/api/client.ts`. Verify with `npm --prefix web run build`.
- [x] 4.2 Render the "Server identity" row in the NetherNet layout of `web/src/sections/Network.tsx` with the three states and the explanation, show the save button only when running, not saved and not in maintenance, and update from the response or show the error inline (design D7). Verify in `web/src/test/network.test.tsx`:
  - saved: no button;
  - not saved and running: the button shows, clicking it shows saved, and no config write is sent;
  - not saved and stopped: the next-start text shows with no button;
  - in maintenance: no button;
  - a failure shows the reason;
  - the RakNet layout has no identity row.

## 5. Docs and checks

- [x] 5.1 Update the README:
  - "Network transport": the identity key, the automatic save, and why it matters for players.
  - "Filesystem layout": `data/keys/`.
  - Backups section: archives contain the private key.

  Add a `CHANGELOG.md` entry under the unreleased heading. Verify by review.
- [x] 5.2 Run the full suites: `.venv/bin/pytest`, `ruff check` on changed files, `ruff format` on your own files only (a clean tree already fails `--check`), and `npm --prefix web test` plus `npm --prefix web run build`. Verify that all of them pass.

## 6. Live verification

- [x] 6.1 On cobble-2, delete any `data/keys/` (as root), deploy the branch, and restart. Verify:
  - after readiness `data/keys/server_identity_key.pem` exists with mode `0600`;
  - `serveridentity status` reports it saved;
  - the console stream shows neither the save command nor its reply;
  - the Network section shows "Saved".
- [x] 6.2 Join from a client, restart the server, and join again. Verify that the second join needs no new trust prompt and succeeds. Then run a Bedrock update or re-activate the same version, and check that the key file's sha256 is unchanged.
