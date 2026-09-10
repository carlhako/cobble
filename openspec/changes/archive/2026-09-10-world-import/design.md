## Context

See proposal.md — Why. The constraints that shape the approach:

- **Restore already does most of this.** `BackupService._restore` stops the server inside a `maintenance_scope`, refuses on an unclean stop, captures and *verifies* the state being replaced, extracts over `data/`, re-establishes the vendor-payload symlinks, re-keys gamerules, and returns the server to its prior run state. Import is the same sequence with a zip instead of a cobble tarball, and a narrower target.
- **`data/worlds/<level-name>/` is the only thing being replaced.** Restore swaps the whole of `data/` and `state_dir/`. Import touches exactly one directory. That is a strictly smaller blast radius, but it means import cannot reuse `_extract_over_layout` as written.
- **Nothing in cobble accepts an upload.** No `UploadFile`, no multipart, no `python-multipart` dependency. This is the first inbound file, and it is operator-supplied rather than a signed vendor download — the trust posture is different from `acquisition.installer`.
- **There is no reverse proxy.** `deploy/` is a systemd unit and an install script; uvicorn is reached directly, so there is no upstream body-size limit to configure or fight.
- **Worlds are a set, `level-name` is a selector.** `ConfigService.worlds()` lists `data/worlds/*` and `apply()` will happily point `level-name` at a name that does not exist yet. There is, however, **no way to delete a world** — which is why import replaces in place rather than adding alongside (D2).
- **The reference archive is not a world export.** The example is a 373 MB Crafty Controller full-server backup whose world (`worlds/Bedrock level/`, 21 MB) sits beside a 243 MB `bedrock_server` binary. Its `level.dat` reports `lastOpenedWithVersion = [1,26,43,1]`, `StorageVersion = 10`, seed `-7302393117572340386`.

## Goals / Non-Goals

**Goals:**

- Accept the archive shapes operators actually have, without asking them to repackage.
- Make the destructive step recoverable by construction, not by discipline.
- Confine every future change needed for resumable chunked upload to the upload phase alone.
- Add no dependency beyond what a multipart-free streaming upload requires.

**Non-Goals:**

- Resumable or chunked upload in this change. The endpoint split makes it additive later (D3).
- A general world manager — creating, renaming, deleting, or switching worlds. Switching is already the configuration screen's job; deleting remains absent.
- Parsing NBT in general. Three fields are read from a known offset structure; a full NBT library is not warranted (D5).
- Exporting a world *out* of cobble. The backup download already serves that need, in cobble's own format.

## Decisions

### D1. Upload and apply are separate endpoints, joined by a staged archive

```
  POST /api/import/upload      stream -> staging/.partial -> rename    { staged }
  GET  /api/import             what cobble found in the held archive
  DELETE /api/import           discard the held archive
  POST /api/import/apply       { confirm_old_version } -> the destructive sequence
```

Three reasons, in order of weight. First, the operator must confirm against the world's *identity* — "you are installing `Bedrock level`, seed −7302393117572340386, last opened with 1.26.43.1, replacing your current `Bedrock level`" — which is only possible once the archive is on disk and inspected. Second, a single endpoint that uploads and imports would hold the server down for the duration of the transfer; a gigabyte over WiFi is minutes of avoidable downtime. Third, it is the seam that makes D3 possible.

**Alternative rejected:** one `POST /api/import` doing everything, with confirmation as a query parameter. Smaller, but the operator would be confirming a filename, and every later improvement to the transfer would touch the import semantics.

### D2. The import replaces `data/worlds/<level-name>` in place; `level-name` is never written

The alternative — extract to a new directory and repoint `level-name` — is non-destructive and was the initial preference. It was rejected because **cobble has no world deletion**: `ConfigService` lists worlds and never removes one, and the API exposes no delete. Every import would strand a full world directory, possibly gigabytes, with no path to reclaim it short of shell access on the host. Replacing in place keeps disk use bounded, and keeps `level-name` stable so gamerule records (keyed by level-name), the configuration screen, and backups all continue to refer to the same thing.

The cost is that the import is genuinely destructive, which is what D4 exists to answer.

Two consequences worth naming:

- **`levelname.txt` is rewritten** to the destination directory name. The reference archive's world is named `Bedrock level` internally; imported into a server whose `level-name` is `MyWorld`, an unmodified `levelname.txt` would leave `worlds/MyWorld/levelname.txt` reading `Bedrock level`. Cosmetic, but it surfaces in server listings and makes `worlds()` misleading.
- **The gamerule re-key is mandatory, not incidental.** The imported `level.dat` carries the source server's gamerules (the reference world has `keepinventory` set). Without `BackupService`'s `on_restored` hook, cobble's next readiness pass would *adopt* those as the server's configured values rather than reasserting its own. Import calls the same hook with the same level-name.

### D3. Streamed single-request upload, shaped so chunking is additive

The upload reads `request.stream()` and writes to `<state_dir>/import-staging/upload.partial`, renaming on completion. Memory is flat at the chunk size regardless of archive size, so **size is a disk problem, not a memory problem** — which is the whole reason chunked upload is not needed for correctness. It is needed only for *resume*, and on a LAN a gigabyte is tens of seconds.

Reading the raw body rather than a multipart form avoids the `python-multipart` dependency entirely and removes a parsing layer from the path an untrusted file travels.

Adding resumable chunking later means adding `POST /api/import/upload/chunk` writing at an offset, plus a received-ranges record. It produces the same staged archive, so inspect and apply are untouched. Recording this here is the point of the decision.

### D4. The safety capture is the existing verified capture, and it gates the destruction

`capture_archive` + `verify_archive` run before a single file is removed, exactly as in `_restore`. If the capture fails or does not verify, the import abandons before touching the world. The capture is a normal backup — it appears in the list, it is restorable through the existing UI, and it is subject to retention.

This is what makes D2's in-place replacement acceptable: the world is never in a state where the old one is gone and no recoverable copy exists.

### D5. The world is found by structure; `level.dat` is read directly

**Locating.** Scan the zip's entry names for any `level.dat` whose sibling `db/` contains `CURRENT`. That single rule covers all three shapes in the wild:

```
  worlds/<Name>/level.dat     full server backup (Crafty, BDS)
  <Name>/level.dat            zipped world folder
  level.dat                   .mcworld / Realms export, at the root
```

Zero matches and more than one match are both refusals, per the spec. Refusing the multi-world case rather than offering a picker keeps the state machine to one world per archive; it can be relaxed later without changing anything else.

**Reading.** `level.dat` is an 8-byte header followed by little-endian NBT. Three fields are needed: `lastOpenedWithVersion` (a 5-int list), `RandomSeed`, and `LevelName`. Locating each tag by its name bytes and decoding the fixed-width payload that follows is a few dozen lines and no dependency. A missing or unparseable field yields `None` and the version check treats it as unknown rather than failing the import — an old or unusual world should still be importable.

**Alternative rejected:** an NBT library. It would be a new dependency, in a security-sensitive path, parsing an operator-supplied file, to read three fields.

### D6. Version compatibility is asymmetric

| Imported world vs installed BDS | Behaviour | Handling |
| --- | --- | --- |
| Older | BDS upgrades the world in place, irreversibly | Warn, proceed on `confirm_old_version` |
| Equal, or unknown | loads normally | proceed |
| **Newer** | may refuse to load, or damage the world | **refuse, not overridable** |

The older case reuses `acquisition.version.is_newer` and mirrors restore's `needs_confirmation` shape exactly, so the frontend's existing two-step confirmation pattern carries over. The newer case is new: restore never faces it, because cobble's own backups cannot come from the future. It is a hard refusal rather than a warning because the failure mode is silent world damage, and because the remedy — update the server first — is available in the interface.

### D7. Extraction is validated member-by-member

`installer._extract` calls `zipfile.extractall()` with no member validation. That is defensible for a checksummed vendor download over TLS; it is not defensible for a file an operator uploaded. Before extracting, every member is checked: no absolute paths, no `..` traversal once normalised against the destination, and no links pointing outside it. A single failing member refuses the whole archive.

Only the located world subtree is extracted — the reference archive's 243 MB `bedrock_server` is never written to disk.

### D8. One staging slot, swept on startup and cleared on apply

A single fixed path, not a session directory keyed by id. A new upload replaces the slot; a completed or failed apply clears it; a sweep at startup discards anything left from a previous run. This removes an entire category of work — no session table, no expiry timer, no orphan GC — at the cost of an operator being unable to hold two archives at once, which is not a use case.

### D9. Free space is checked twice, with different budgets

Before the upload: room for the archive. Before the apply: room for the extracted world *plus* the safety capture, since both exist simultaneously with the world being replaced. The apply-time check happens before the server is stopped, so a refusal costs no downtime. Sizes come from the zip's uncompressed member totals for the located subtree and the current world's on-disk size; a margin is applied because the capture is compressed by an unpredictable ratio.

The failure this prevents is the bad one: a half-extracted world and a stopped server.

### D10. The frontend uses `XMLHttpRequest` for the upload only

`client.ts`'s `request()` wrapper is `fetch`-based, and `fetch` cannot report upload progress — request streaming needs `duplex: 'half'` and is not usable across the browsers this targets. `XMLHttpRequest.upload.onprogress` is the only reliable byte counter. This is a deliberate, documented exception confined to one function; every other import call goes through the existing wrapper.

## Risks / Trade-offs

- **The import is destructive by design (D2)** → the safety capture is taken and verified before anything is removed (D4), it is a first-class restorable backup, and the confirmation names the world being destroyed as well as the one being installed.
- **A failure between "world removed" and "world extracted" leaves no world** → the failure report names the safety capture, and the operator restores it through the existing UI. Making the swap atomic would require extracting to a sibling directory first, doubling peak disk use; given the capture already exists, that trade is not worth it. Extraction happens before removal where the disk budget allows it — noted as a task, not a guarantee.
- **A world may be too damaged to load even though it imported cleanly** → cobble validates structure, not chunk integrity, and cannot know before starting BDS. The safety capture is the recovery path; the spec does not promise the imported world is playable.
- **`lastOpenedWithVersion` may not track BDS's own versioning forever** → the reference world reports `1.26.43.1` while its `InventoryVersion` reads `1.21.131`, so these are separate number lines. Only `lastOpenedWithVersion` is compared against the installed BDS version, and an unreadable value degrades to "unknown" rather than to a wrong decision.
- **A gigabyte upload with no resume can be lost to a dropped connection** → accepted for this change; the transfer is LAN-local and D3 keeps the remedy additive.
- **Disk estimates are approximations** → margins are deliberately generous, and the apply-time check runs before the server is stopped so being wrong costs a refusal rather than an outage.

## Migration Plan

Nothing to migrate. The feature is additive: a new router, a new frontend section, and a staging directory created on demand under `state_dir`. No existing data is touched by deploying it, and no schema, config key, or on-disk layout changes.

Rollback is removing the router registration and the nav entry. Any archive left in the staging slot is inert and is swept by the next startup, or removable by hand.

## Open Questions

- **Should the safety capture be exempt from retention pruning?** A pre-import capture is the only copy of a world the operator has just destroyed, and retention could in principle prune it. Restore has the same exposure today and has not been a problem in practice, so this follows restore's behaviour rather than diverging. Worth revisiting for both paths together if retention is ever set very low.
- **Should a multi-world archive offer a picker instead of refusing?** Refusal is correct for the archives seen so far. If operators turn out to hold multi-world Crafty backups routinely, adding a world selector extends the inspect response and the confirmation without changing the import sequence.
