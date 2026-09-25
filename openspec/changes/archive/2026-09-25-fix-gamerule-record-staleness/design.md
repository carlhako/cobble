# Design

## Context

See proposal.md (Why) for the bug. The relevant current state:

- `GameruleManager.reconcile()` runs once per readiness. It is the only place that decides baseline / adoption / repair / defaults, and until this change it is the only place the record is written during a session. The pre-stop sample (`_on_pre_stop`) never completes because `Supervisor.stop()` switches to STOPPING before the queued read runs.
- `GameruleManager.write_rule()` (running path) sends the command, re-reads the rules, and returns them. It does not touch the record.
- `GameruleManager.current_view()` (behind `GET /api/gamerules`) reads live when running. It reads the report *before* the live read and never writes the record.
- The web section (`web/src/sections/Gamerules.tsx`) calls `GET /api/gamerules` on mount, on a running-state change, and whenever the status push carries a new `last_read_at` or report `created_at`. There is no timed poll. D4's "poll while the section is open" was never built in the UI.
- Readiness reconciliation has ordering constraints: the restore marker must lead to repair, not adoption; a world with no record must get the preferred defaults; queued stopped-server writes must be applied on top. All of these assume readiness is the first thing to touch the record in a run.

## Goals / Non-Goals

**Goals:**

- Cobble's own writes never produce an adoption report.
- A live read reports an in-game change once, at that read, and readiness does not report it again.
- The readiness decisions (repair after restore, defaults on first sight, pending writes) are unaffected by a write or live read that races the start.

**Non-Goals:**

- A timed poll in the web UI. Live reads happen when the UI already fetches.
- Detecting changes typed into cobble's own console as "cobble's". They go through the operator console, not the gamerule service, so they are still adopted and reported. Live check 7.3 relies on this.
- Making the pre-stop hook synchronous or awaited (option B from exploration).

## Decisions

### D1: One lock around every record-touching gamerule operation

An `asyncio.Lock` on the manager is held by `reconcile()`, by the whole running path of `write_rule()` (send, re-read, save record), and by the reconcile step in `current_view()`.

*Why:* without it, a GET that lands between `write_rule` sending the command and saving the record would see the new value, find it differs from the record, and adopt cobble's own write, which is the bug again through a different path. The same interleaving applies between readiness and a GET.

*Alternative rejected:* a "cobble just wrote X" short-lived set that the diff excludes. It solves only the write race, needs expiry rules, and still leaves readiness exposed.

### D2: Live reads and writes touch the record only after this run's readiness reconcile

The manager tracks whether the current run has been reconciled. The flag is cleared synchronously in `on_event` when `SERVER_READY` arrives, before the supervisor reaches RUNNING, so no live read can slip in first. It is set when `reconcile()` finishes with any outcome other than UNAVAILABLE or STORAGE_ERROR.

- `current_view()` before reconciliation: serve the live set as today and leave the record and report alone. It does not take the lock, so a page load never waits behind the readiness reconcile.
- `write_rule()` before reconciliation: wait for reconciliation, bounded at about 10s, then write and save the record. If the wait times out (readiness reconcile failed or is stuck), send the write and still save the re-read set as the record. At worst that is a baseline taken slightly early, which is better than a false adoption later. The maintenance refusal and the running/stopped choice are made again once the wait and the lock are over, so a write never lands during a backup or restore that began meanwhile, and is queued if the server stopped.

*Why:* this leaves every existing readiness branch exactly as it was. The restore marker, first-sight defaults, and pending writes are all handled before anything else can write the record. Checking those three conditions separately in the live path would duplicate `reconcile()`'s branching.

*Alternative rejected:* have `current_view()` call the full `reconcile()`. That would re-apply pending writes and consume the restore marker on an ordinary page load.

### D3: The live-read reconcile is the adoption branch only

With the run reconciled, `current_view()` diffs live against the record:

- differs: write the record and an adoption report naming only the changed rules, then notify status (`_record_report` already does this);
- matches: leave the record alone. Rewriting it would only move `sampled_at`, which is the status payload's `last_read_at` and makes every open Gamerules section reload.

It reads the report *after* this step so the response includes a report it just created. Pending writes cannot exist while running (they are consumed at readiness and `write_rule` does not queue while running), so the diff needs no pending exclusion. It still goes through the same `_diff` helper.

The same step runs on the re-read that follows a write while running, excluding the written rule: any other rule that differs was changed in game since the last read and is adopted, not silently folded into the record. When a write is sent but its re-read is lost, the written value is laid over the prior record, so it is not later reported as an outside change.

An adoption that is still unacknowledged is extended rather than replaced, so a rule it named is not dropped before the operator sees it. Readiness adoption goes through the same `_adopt`.

A repair re-reads after re-applying. A value the server refused stays as the restore left it, so the re-read set becomes the record and the repair report names only what was put back; otherwise the first live read would report the refused rule as an in-game change.

*Why:* repair and defaults are one-off readiness decisions (D2). After readiness, the only unexplained divergence is an in-game (or cobble-console) change, which is exactly adoption.

### D4: Remove the pre-stop sample

Delete `_on_pre_stop`, `_safe_sample`, and the `subscribe_pre_stop` call, along with the unit tests that exercised them against the fake. `sample_and_store()` has no other caller and goes too.

*Why:* it has never run. If it ever did, it would silently write in-game changes into the record, and they would never be reported. With D2 and D3, the record at stop already holds the last value cobble read or wrote.

### D5: Fake supervisor matches real stop ordering

`tests/gamerules/fakes.py` switches its state to STOPPING before calling pre-stop listeners, as `Supervisor.stop()` does. Nothing in the gamerule manager subscribes any more, but the fake is shared and should not hide this class of bug again.

## Risks / Trade-offs

- [A slow `GET /api/gamerules` while a write holds the lock] → Writes complete in a few seconds (2s write-reply timeout plus a 5s read at worst). A GET waiting behind one is acceptable, and the UI already shows a busy state for the row being written.
- [`sampled_at` no longer moves on a matching live read] → The stopped view's "recorded on" date is when the values were last recorded, not last read. The values are the same either way.
- [Records already stale from before the fix] → The first live read after the upgrade would report the old write as an adoption once. Accepted: it is a single report that can be acknowledged, and it is accurate in the sense that the record did differ. No migration.
- [Readiness reconcile returns UNAVAILABLE, so no live-read reconciliation for that run] → Same as today (nothing was being updated during a session anyway). Logged at info, as it is now.
