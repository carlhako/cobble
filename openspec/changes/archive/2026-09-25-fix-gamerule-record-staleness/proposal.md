# Proposal

## Why

Changing a gamerule in the cobble panel while the server runs, then restarting the server or upgrading cobble, shows "A gamerule was changed outside cobble" for the change the operator just made. The per-world record is never updated during a session. A successful write does not save it. The pre-stop sample never completes because the supervisor switches to STOPPING before the queued read runs, so the console refuses it. The next readiness then sees cobble's own write as an unexplained divergence and adopts it.

## What Changes

- A successful gamerule write through cobble saves the re-read set as the active world's record, so cobble's own changes are never reported as made outside cobble.
- A live read of the gamerule set (the section being open, or its poll) reconciles against the record. A match refreshes the record. A divergence is adopted and reported immediately, as it would be at readiness. An in-game change is then reported when someone is looking, not only at the next restart.
- The pre-stop sample is removed. It has never completed. If it did work, it would quietly absorb in-game changes into the record, so they would never be reported, which contradicts adoption-and-report.
- The test fake supervisor switches to STOPPING before notifying pre-stop listeners, matching the real ordering. New tests cover "write while running, restart, no report".
- Live check 7.2 also asserts that no report is present after the restart.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `server-gamerules`: the record is kept current by cobble's own writes and by live reads, not by a pre-stop sample. A live read that diverges from the record adopts and reports, the same as readiness.

## Impact

- `src/cobble/gamerules/manager.py`: `write_rule`, `current_view`, removal of `_on_pre_stop` / `_safe_sample`, and the pre-stop subscription.
- `tests/gamerules/fakes.py`, `tests/gamerules/test_manager.py`: fake stop ordering, new and removed tests.
- `tests/live/verify_gamerules.py`: 7.2 gains a no-report check.
- No API shape or storage schema change. Existing stale records correct themselves on the next write or live read. A report already shown can be acknowledged as usual.
