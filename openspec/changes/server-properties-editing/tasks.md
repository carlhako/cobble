## 1. Properties document

- [x] 1.1 Implement a `server.properties` parser that models the file as an ordered sequence of classified lines — comment, blank, and key/value assignment — retaining each line's original text (design.md D1); verify a file containing comments, blank lines, indentation, and inline `=` characters in values round-trips through parse and serialize byte-for-byte
- [x] 1.2 Implement the effective-value view over a parsed document, resolving a repeated key to its last assignment as BDS does (design.md D1); verify a document with a key assigned twice reports the second value, and that both assignment lines are still present in the document
- [x] 1.3 Implement in-place value mutation that rewrites only matched assignment lines and appends a genuinely new key at the end; verify changing one value leaves every other line — including comments and unrecognised keys — identical, and that writing to a repeated key updates the last occurrence only
- [x] 1.4 Implement atomic persistence via a temporary file in `data/` renamed into place (design.md D7); verify an interrupted write leaves the previous content intact and that no partially written file is ever observable

## 2. Property schema and validation

- [x] 2.1 Define the property schema table — key, type (bool / int / enum / string), documented default, permitted values or range, and a short description — covering the keys BDS ships in `server.properties` (design.md D2); verify every key present in a freshly extracted vendor `server.properties` is either in the table or deliberately absent from it
- [x] 2.2 Implement lookup that classifies a key as recognised or unrecognised, so unrecognised keys remain editable as text (design.md D2); verify a key absent from the schema is reported with its value and marked unrecognised rather than being dropped or rejected
- [x] 2.3 Implement type and enum validation that rejects a write with a per-key reason and changes nothing (server-config: "Submitted values are validated"); verify a non-integer in an integer field, a non-boolean in a boolean field, and a value outside an enum's member set are each rejected, that several invalid values are all reported in one response, and that the stored file is unchanged
- [x] 2.4 Implement range checking that accepts an out-of-range value of the correct type and returns a warning naming the setting and expected range (design.md D3); verify the value is persisted and the warning is returned

## 3. Configuration service

- [x] 3.1 Implement reading the configuration as settings carrying key, value, and — for recognised keys — type, default, and permitted values or range; verify a read returns every setting in the file and succeeds while the server is stopped
- [x] 3.2 Implement the write path applying a batch of changes all-or-nothing over the parsed document, persisting via 1.4; verify a batch containing one invalid value persists none of the batch, and that a batch of valid values persists all of them
- [x] 3.3 Reject writes while a maintenance operation is in progress using the existing maintenance error, while leaving reads available (server-config: "Configuration writes are refused during maintenance"); verify a write during an update or restore fails with the maintenance code and leaves the file unchanged, that a read during maintenance succeeds, and that writes are accepted again once maintenance ends
- [x] 3.4 Implement enumeration of the worlds under `data/worlds/`, identifying which one the level setting names and marking a named world that does not exist (design.md D4); verify the current value is still reported when its directory is absent, and that an empty `worlds/` returns an empty set without error
- [x] 3.5 Report, on a write that points the level setting at a name with no existing world, that a new empty world will be created at next start; verify the write is accepted and carries that statement

## 4. Configuration in effect and pending changes

- [x] 4.1 Capture the effective configuration map when the supervisor spawns BDS and hold it for the life of that process (design.md D5, `_spawn_and_await_ready`); verify the snapshot is taken at each start, replaced on restart, and absent while the server is not running
- [x] 4.2 Implement the pending-changes comparison between the file on disk and the snapshot, reporting each differing setting with its saved and in-effect values (server-config: "Saved configuration that differs from the running server is reported"); verify a change made through cobble and a change made by writing the file directly both appear, that a comment-only or reordering edit produces none, and that nothing is pending while the server is stopped
- [x] 4.3 Clear pending changes across a restart without an explicit reset step; verify that restarting after a change reports nothing pending, and that the result follows from the new snapshot rather than from a flag being cleared

## 5. Status integration

- [x] 5.1 Add a configuration view to `StatusSnapshot` reporting whether changes are pending and how many settings differ, following the existing per-domain view pattern in `status/tracker.py`; verify status reports the count while the server runs with differing settings and reports nothing pending while stopped
- [x] 5.2 Push the pending state to connected clients when configuration is saved and when the server starts or restarts (server-status: "Pending configuration changes are reported"); verify a connected client observes the change without polling in each of those three cases

## 6. HTTP interface

- [x] 6.1 Add a configuration router registered under the single `/api` router with the shared `auth_guard`, following `api/updates.py`; verify the routes appear under `/api` and carry the same dependency as every other state-changing route
- [x] 6.2 Implement the read route returning the settings, their schema metadata, and the pending comparison; verify the response covers recognised and unrecognised settings and is correct with the server both running and stopped
- [x] 6.3 Implement the write route returning per-key rejections, warnings, and the resulting pending state; verify an invalid write returns the failing settings and changes nothing, a valid write returns warnings where applicable, and a write during maintenance returns the maintenance conflict
- [x] 6.4 Implement the worlds route backing the level selection; verify it lists the existing worlds, marks the current one, and marks a current value with no directory

## 7. Web interface

- [x] 7.1 Add a Configuration section and register it in `web/src/sections.tsx`; verify it appears in navigation and that no change to `App.tsx` was required (web-ui-shell: "a new section is added")
- [x] 7.2 Render recognised settings with an input matching their type and their default and description available, and unrecognised settings as editable text marked as unrecognised; verify each type renders its appropriate control and that an unrecognised key is editable
- [x] 7.3 Implement save with per-setting validation errors and warnings, retaining the operator's entered values on rejection; verify a rejected save keeps the entered values and shows the reason against each failing setting
- [x] 7.4 Present the level setting as a picker over existing worlds with "create a new world" as a separate, explicitly labelled and confirmed action (design.md D4); verify the picker lists existing worlds, that creating a new world states the existing worlds are kept and requires confirmation, and that a current value with no directory is shown as missing
- [x] 7.5 Present pending changes with a restart offer that can be deferred, stating that deferred changes take effect at the next start for any reason (design.md D6); verify accepting restarts and clears the pending state, declining keeps it visible with that statement, and no restart is offered when the server is stopped
- [x] 7.6 Show the pending state when the interface is opened with changes already pending, including which settings differ and their saved and in-effect values; verify a freshly loaded interface shows the pending state without the change having been made in that session
- [x] 7.7 Disable saving during maintenance with the operation named, re-enabling it when maintenance ends; verify settings remain visible, saving is not offered, and it becomes available again without a refresh

## 8. Verification

- [x] 8.1 Exercise the full loop end to end against a running server: save a setting, observe it pending, restart, observe it in effect and no longer pending; verify with a setting whose effect is visible in BDS output or status
- [x] 8.2 Verify a deferred change is applied by a start cobble did not initiate — a crash restart or an update — and that the pending state clears as a result (design.md D6)
- [x] 8.3 Verify a hand-edited `server.properties` containing comments and operator-added keys survives a save from the interface with only the changed line altered, by diffing the file before and after
- [x] 8.4 Verify the level picker against a server with two worlds: switching between them loads each world, and both directories remain on disk throughout
- [ ] 8.5 Run the full check suite — `ruff check . && ruff format --check .`, `pytest`, `npm --prefix web run lint`, `npm --prefix web run test`, `npm --prefix web run build` — and verify all pass
- [x] 8.6 Update `README.md` to document configuration editing and the restart-to-apply behavior; verify the described behavior matches what ships
