## 1. The silent console path

- [x] 1.1 Add a non-echoed submission entry point to `Console` that shares `_command_lock` and the running-state check with `submit_command` but does not call `_buffer.add_command`; verify a unit test asserts the command reaches the supervisor's stdin and that no subscriber receives a console line for it
- [x] 1.2 Add one-shot reply capture: the caller registers a line matcher before submission, and the first matching line within a bounded timeout is returned to the caller and withheld from console fan-out (design.md D3); verify a test asserts the matched line is returned once and appears in no subscriber's stream
- [x] 1.3 Pass through every line that does not match while a query is outstanding; verify a test interleaves unrelated server output with a query and asserts only the reply is withheld
- [x] 1.4 Abandon a query that produces no matching line within the timeout, reporting failure without raising into the stdout pump; verify a test with a server that never replies asserts the caller gets a failure and the console keeps delivering output
- [x] 1.5 Log any line the matcher consumes, so a false match is diagnosable (design.md Risks); verify a test asserts the consumed line is logged
- [x] 1.6 Refuse an internal query when the server is not running, without queuing it; verify a test asserts the failure and that the console stream is untouched
- [x] 1.7 Confirm the API console router cannot reach the silent path; verify a test asserts a client-submitted command is always echoed regardless of its content

## 2. Reading and writing gamerules

- [x] 2.1 Create the `cobble.gamerules` package with the static rule catalogue — name, type (bool / int / enum), range or member set, default, and description — covering the 39 rules recorded in design.md Context; verify a test asserts every catalogued rule has a type and that integer rules carry their bound
- [x] 2.2 Implement the bulk-dump parser: split an `INFO` reply on `, `, split each pair on ` = `, and return canonical name/value pairs; verify a test parses the verbatim 39-rule line from design.md Context and asserts all 39 names and values, including `playerWaypoints = everyone` and `maxCommandChainLength = 65535`
- [x] 2.3 Coerce parsed values by catalogue type and carry an uncatalogued rule through as raw text marked unrecognised (design.md D9); verify a test asserts a booleans-as-bool, ints-as-int result and that an injected unknown rule survives with its raw value and its unrecognised marker
- [x] 2.4 Implement the bulk read — issue `gamerule` on the silent path with a shape matcher requiring several ` = ` pairs, and return the parsed set; verify a test with a fake server asserts the issued command is exactly `gamerule` and that the parsed set is returned
- [x] 2.5 Implement the write — issue `gamerule <name> <value>`, discard any acknowledgement, then perform a bulk read and report the value it returns (design.md D1, D2); verify a test asserts no single-rule query is ever issued and that the reported value comes from the bulk read
- [x] 2.6 Assert correctness with acknowledgements suppressed; verify a test whose fake server emits no output for a write still reports the write's outcome correctly from the re-read
- [x] 2.7 Pre-validate a submitted value against the catalogue — wrong type, out of range, or not an enum member — and refuse without sending anything to the server; verify tests cover each rejection and assert no command was issued
- [x] 2.8 Surface a server-side refusal verbatim and leave the record unchanged; verify tests drive the three observed error forms from design.md Context (syntax error on value, syntax error on rule name, number-too-big) and assert each reaches the caller with the record untouched

## 3. The per-world record

- [x] 3.1 Add tables to `cobble.db` for the per-world gamerule record (keyed by level-name, with the time sampled), the operator's preferred defaults, the pending restore marker, and the unacknowledged report; verify a test opens a temporary database twice and finds the schema unchanged the second time
- [x] 3.2 Implement record read and write per world, and a query for whether a world has ever been recorded; verify a test asserts two worlds keep independent records and that an unrecorded world is reported as unread rather than empty
- [x] 3.3 Sample and store the live set on server readiness; verify a test asserts a record is written for the active world with the readiness time
- [x] 3.4 Sample opportunistically on the existing pre-stop hook, best-effort, leaving the previous record standing on failure (design.md D4); verify a test asserts a completed sample is stored and that a failing one leaves the prior record and its timestamp intact
- [x] 3.5 Serve the recorded set when the server is not running, marked as recorded with the time taken, and report an unrecorded world as unread; verify tests cover both cases and assert no values are invented for an unread world
- [x] 3.6 Make every gamerule storage failure logged and non-raising; verify a test with a storage layer that raises asserts the server and the readiness path are unaffected

## 4. Adoption, repair, and defaults

- [x] 4.1 Implement the readiness reconciliation that compares the live set against the record and classifies the outcome as baseline, adoption, repair, or first-sight defaults (design.md D5, D6, D8); verify a test drives each of the four classifications and asserts the branch taken
- [x] 4.2 Adopt a divergence — store the live values, change nothing on the server, and record an unacknowledged report naming each rule and its new value; verify a test asserts the server received no write and that the report lists exactly the diverged rules
- [x] 4.3 Set the restore marker from the restore path, naming the world restored; verify a test asserts a completed restore writes the marker and that a failed restore does not
- [x] 4.4 Consume the marker on the first readiness after it is set and, on a divergence, re-apply the recorded values and record a repair report; verify a test asserts the recorded values are written back, the report names them, and the marker is cleared even when no divergence is found
- [x] 4.5 Confirm the start after a repair adopts again; verify a test runs two consecutive readiness cycles and asserts the second classifies a divergence as an adoption
- [x] 4.6 Apply preferred defaults to a world with no record, store the resulting set as that world's baseline, and record a report; verify a test asserts the defaults are written to the server, become the record, and are reported
- [x] 4.7 Confirm defaults never reach a recorded world and that a first-sight world with no defaults set is simply recorded as-is; verify tests cover both
- [x] 4.8 Refuse gamerule writes during maintenance while keeping reads available; verify tests assert a write raises the maintenance error naming the operation and that a read succeeds

## 5. API

- [x] 5.1 Add `/api/gamerules` returning the active world's set with its liveness (live, recorded with a timestamp, or unread) and each rule's type and recognition; verify a test asserts the shape for a running server, a stopped server with a record, and an unread world
- [x] 5.2 Add the write route, depending on `auth_guard` as the other state-changing routers do; verify a test asserts a successful write returns the re-read value and that a refusal returns a per-rule reason
- [x] 5.3 Add routes to read and edit the preferred defaults; verify tests cover setting, clearing, and reading them back
- [x] 5.4 Add the acknowledge route that clears an unacknowledged report without changing any recorded value; verify a test asserts the report is gone from status and the record is untouched
- [x] 5.5 Queue a write submitted while the server is stopped as the intended value for that world and apply it at the next start; verify a test asserts the value is stored, no command is issued, and it is written on the following readiness
- [x] 5.6 Add the gamerules block to the status payload — active world, liveness, last read time, and any unacknowledged report; verify a test asserts the block appears in `/api/status` and that a status stream event is emitted when a report is recorded

## 6. Web interface

- [x] 6.1 Add a `Gamerules.tsx` section rendering each rule by type — checkbox, bounded number, enum select, and plain text for an unrecognised rule — and register it in `sections.tsx`; verify a component test asserts one control of each kind renders from a fixture set
- [x] 6.2 Apply a change immediately and display the value returned by the re-read, with no restart prompt; verify a test asserts the displayed value follows the server's response rather than the submitted one
- [x] 6.3 Show a refusal against its rule and revert the displayed value to the one in effect; verify a test asserts the reason is shown and the control returns to its prior value
- [x] 6.4 Present recorded values as recorded, with the time taken, and an unread world as unread rather than showing values; verify tests cover the stopped-with-record and never-run cases
- [x] 6.5 State that a change made while stopped will apply at the next start; verify a test asserts the message appears when the server is not running
- [x] 6.6 Surface an adoption, repair, or defaults report with its rules and values, and an acknowledge control that dismisses it; verify a test asserts each report kind renders and that acknowledging removes it
- [x] 6.7 Add the preferred-defaults editor, presented separately from the active world's values and stating that it applies only to worlds not seen before; verify a test asserts the separation and the wording
- [x] 6.8 Disable editing during maintenance while keeping values visible, and re-enable without a reload when maintenance ends; verify a test drives a status change in each direction and asserts the transition

## 7. Documentation and live verification

- [x] 7.1 Add a Gamerules section to the README covering immediate application, per-world records, adoption versus repair, preferred defaults, and the unread state; verify the section is present and consistent with the specs
- [x] 7.2 Extend the live harness with a gamerules check that reads the set, writes a rule, confirms by re-read, restarts, and asserts the value survived; verify it passes against the live host
- [x] 7.3 Add a live check that a gamerule change made outside cobble is adopted and reported on the next readiness; verify it passes against the live host
- [x] 7.4 Add a live check that a restore is followed by a repair rather than an adoption; verify it passes against the live host
- [x] 7.5 Confirm the recorded Bedrock output formats still hold on the installed version and that no bulk read or write appears in the operator console; verify by inspecting the console stream during the live run
