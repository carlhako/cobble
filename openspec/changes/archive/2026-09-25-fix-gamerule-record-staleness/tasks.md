# Tasks

## 1. Test scaffolding

- [x] 1.1 Change `tests/gamerules/fakes.py` so the fake supervisor switches to STOPPING before notifying pre-stop listeners (design D5); verify `pytest tests/gamerules` still collects and the existing non-pre-stop tests pass
- [x] 1.2 Add a failing test in `tests/gamerules/test_manager.py`: readiness baseline, `write_rule` while running, then a second readiness produces no adoption report and the record holds the written value; verify it fails on the current code

## 2. Manager: serialise and gate record updates

- [x] 2.1 Add the manager lock and hold it across `reconcile()` and the running path of `write_rule()` (design D1); verify existing reconcile tests still pass
- [x] 2.2 Add the per-run "reconciled" state: cleared synchronously in `on_event` on `SERVER_READY`, set when `reconcile()` finishes with an outcome other than UNAVAILABLE / STORAGE_ERROR (design D2); verify with a unit test that the flag is cleared before the ready task runs
- [x] 2.3 In `write_rule()`'s running path, wait (bounded, ~10s) for reconciliation, then save the re-read set as the active world's record (design D2); verify test 1.2 now passes, plus a test that a write racing readiness on a first-sight world with preferred defaults still gets a DEFAULTS outcome

## 3. Manager: live-read adoption

- [x] 3.1 In `current_view()`, after a successful live read in a reconciled run and under the lock, diff against the record: on divergence write the record and an adoption report naming only the changed rules; on a match refresh the record (design D3); verify with tests for both branches
- [x] 3.2 Read the report after that step so the returned view includes a report it just created; verify with a test that the first GET after an in-game change returns the adoption report
- [x] 3.3 Test that an in-game change adopted at a live read is not reported again at the next readiness (spec: "A change in game is reported while the server runs")
- [x] 3.4 Test that `current_view()` before reconciliation leaves the record, restore marker, and report untouched, and that a restore followed by a racing GET still ends in REPAIR at readiness
- [x] 3.5 Test that a GET issued while a write is in flight does not adopt the write (lock ordering, design D1)

## 4. Remove the pre-stop sample

- [x] 4.1 Delete `_on_pre_stop`, `_safe_sample`, `sample_and_store`, and the `subscribe_pre_stop` call from `GameruleManager`, and remove their tests (`test_pre_stop_stores_a_completed_sample`, `test_failing_pre_stop_sample_leaves_the_prior_record_intact`) (design D4); verify `grep -rn "sample_and_store\|_on_pre_stop" src/cobble/gamerules tests/gamerules` is empty and `pytest tests/gamerules` passes
- [x] 4.2 Update the module docstring in `manager.py` to describe when the record is written (readiness, cobble writes, live reads); verify by reading it

## 5. Verification

- [x] 5.1 Run the full Python suite (`pytest`) and `ruff check` on the changed files; verify both are clean (format only the files you touched)
- [x] 5.2 Extend `tests/live/verify_gamerules.py` 7.2 to assert no report is present after the restart; verify the script still parses (`python -m py_compile`)
- [x] 5.3 Run the live gamerule checks against the test LXC (7.2, 7.3, 7.4); verify all pass, including the new no-report check in 7.2 and the adoption in 7.3
- [x] 5.4 Manual check on the LXC: change keepInventory in the panel, restart the server, then upgrade/restart cobble; verify no "changed outside cobble" panel appears either time
