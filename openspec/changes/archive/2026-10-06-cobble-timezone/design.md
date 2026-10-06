# Design

## Context

See proposal.md (Why). The current state that shapes the approach:

- `src/cobble/schedule.py` computes next runs from `clock=datetime.now`, which returns a naive time in the process's zone. `_next_after()` builds candidates with `now.replace(hour=, minute=)` and `+ timedelta(days=)`. The loop sleeps for `(nxt - self._clock()).total_seconds()`, a naive subtraction that is wrong by the DST shift across a transition. Only the 15-minute `_MAX_SLEEP` re-evaluation hides that.
- `src/cobble/status/tracker.py` sends `nxt.isoformat()` with no offset. The web UI's `fmtTime()` does `new Date(iso).toLocaleString()`, so a naive string is read as browser-local. That is why cobble-3 showed "4:00 AM" while running at 04:00 UTC.
- Live evidence on cobble-3 (v0.7.4): `backup.last_at` and `update.last_check_at` are both `2026-10-06T04:00:00…+00:00` for a 04:00 schedule, so the process zone has a +00:00 offset. In October that means UTC, not Europe/London.
- `MaintenanceSettingsStore` (`maintenance_settings.json`) is server state that a restore brings back. `INSTANCE_LOCAL` in `src/cobble/backup/artifact.py` lists the state-dir entries a restore leaves alone.
- `/api/cobble` (`src/cobble/api/cobble.py`) already holds cobble-level endpoints (version, check, upgrade). The cobble page (`web/src/sections/Cobble.tsx`) is reached only from the header version badge.

## Goals / Non-Goals

**Goals:**
- Schedule maths gives the same result whatever the process's zone is: the only zone input is the effective cobble timezone.
- Every comparison and sleep is done on absolute instants, so DST cannot produce a skipped or a repeated run.
- Keep the existing scheduler shape: cursor-based next-run computation, the jitter grace, deferred-from handling, coordinated windows.

**Non-Goals:**
- Migrating stored timestamps. Everything persisted today is already UTC-aware.
- A general preferences framework. The store holds the timezone only, and gains fields as later settings arrive.

## Decisions

### D1. A separate, instance-local `cobble_settings.json`

A new `CobbleSettingsStore` at `state_dir / "cobble_settings.json"` holds `{"timezone": "<IANA name>" | null}`, written with the same tmp-file-and-rename approach as the other stores. A `CobbleSettingsService` resolves the effective zone and has an on-change hook, like `MaintenanceSettingsService.set_on_change`. The scheduler registers `reschedule_now` with that hook.

`cobble_settings.json` is added to `INSTANCE_LOCAL`. Captures still include it, as they include the other instance-local files, but a restore keeps the destination's copy.

- *Alternative*: a `timezone` field in `maintenance_settings.json`. Rejected, because that file is restored with a backup and the operator wants the zone to stay with the instance.
- *Alternative*: a `COBBLE_TIMEZONE` env var only. Rejected as the primary mechanism, because it is not editable from the panel and needs root to change. It is not added as a fallback either, since the host zone already covers the unset case.

### D2. Effective zone and host-zone detection

The effective zone is `ZoneInfo(set_name)` when a name is set. Otherwise it is the host zone, resolved in this order:
1. The `TZ` env var, if it is a valid IANA name.
2. `/etc/timezone`.
3. The target of the `/etc/localtime` symlink, after `zoneinfo/`.
4. Failing those, the process's fixed local offset (`datetime.now().astimezone().tzinfo`), reported by its offset (for example `+00:00`).

The host zone is resolved per call rather than cached, so it is cheap and stays correct if the host is reconfigured. It is used only when no zone is set.

Validation is `name in zoneinfo.available_timezones()`, plus a successful `ZoneInfo(name)`. The full name list is served to the UI from `GET /api/cobble/settings` (about 600 strings), so the picker matches what the server accepts.

### D3. Zone-aware next-run maths: wall-clock in, UTC out

The scheduler's clock becomes `clock: Callable[[], datetime] = lambda: datetime.now(UTC)`, always aware and always UTC. Then:

```
now_utc  = clock()
now_loc  = now_utc.astimezone(zone)
for each candidate date d (today, or the next matching weekday/month day, then later ones):
    cand_loc = datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone, fold=0)   # built fresh
    cand_utc = cand_loc.astimezone(UTC)
    if cand_utc > after_utc: return cand_utc
```

The rules, and why each matters:

- **Build candidates fresh, with `fold=0`.** Never use `now.replace(...)`. During a repeated hour, `now` has `fold=1`, and `replace` keeps it. A candidate for "02:30" would then resolve to the *second* 02:30, which is still in the future after the first one has run, and the schedule would run twice. A fresh `fold=0` always means the first occurrence.
- **Compare in UTC.** Python compares two aware datetimes that share a `tzinfo` by wall-clock time and ignores `fold`, so `fold1 > fold0` is `False` for the two 02:30s. Every `>`, `<=`, the `_JITTER_GRACE` window and the deferred-from check run on UTC values.
- **Spring-forward gap needs no special code.** A `fold=0` wall-clock time in the gap converts using the offset in force before the transition, so 02:30 becomes 03:30 local time (checked with Australia/Sydney on 2026-10-04: `02:30` resolves to `16:30Z`, which is `03:30+11:00`). That is the "shift by the gap" rule in the spec. It runs once and keeps the spacing between schedules.
- **Advance by date, not by `timedelta`.** "The next day" means building the next calendar date's candidate fresh, rather than `cand + timedelta(days=1)`, so a transition between two runs cannot shift the clock time.
- **Sleep on UTC.** `delay = (nxt_utc - clock()).total_seconds()` is exact across transitions. `_MAX_SLEEP` stays, as the way a settings or host change is picked up.

`backup_next_run()` and `update_next_run()` return UTC instants. The tracker converts them to the effective zone for reporting: `nxt.astimezone(zone).isoformat()` gives `2026-10-07T04:00:00+10:00`, with the offset that applies at that instant.

- *Alternative*: run a gap-time schedule at the end of the gap (03:00), as Vixie cron does. Not chosen. It needs a special case, it moves two gap-time schedules onto the same minute, and "an hour later than usual on the change day" is just as easy to explain.
- *Alternative*: keep naive maths and set `TZ` on the process. Rejected, because it isn't live-changeable and it keeps the naive comparison traps.

### D4. API shape

- `GET /api/cobble/settings` returns `{timezone: str | null, host_timezone: str, effective_timezone: str, effective_offset: "+10:00", timezones: [str, ...]}`.
- `PUT /api/cobble/settings` takes `{timezone: str | null}`. It returns 422 with a message for an unknown name. On success it returns the same body as the GET, calls the on-change hook, and pushes a status update so open panels refresh their next-run times.
- `next_scheduled_at` in status (backup and update) carries the offset, as above. `GET /api/maintenance/settings` and its schedule shape are unchanged: `time` stays `"HH:MM"` and is interpreted in the effective zone.

### D5. Web UI

- **Header cog**: a `NavLink` to `/cobble`, right-aligned (`margin-left: auto`) in the brand row, with `aria-label="cobble settings"`. It uses the active-link styling when it matches, and does not wrap down with `.app-nav` at phone width.
- **Cobble page**: a `CobbleSettings` card is rendered first, above the version, release notes and upgrade content. It has:
  - a filterable timezone select whose first option is "Host default (<host_timezone>)"
  - the effective zone and offset
  - a "Use my browser's timezone (<zone>)" button, shown only when the zones differ (D6)
- **Schedule editors**: the time label reads "Time (Australia/Brisbane)". Next-run times use `Intl.DateTimeFormat(undefined, {timeZone: effective_timezone, dateStyle: "medium", timeStyle: "short"})` and append the zone name. The UI reads the effective zone from the cobble settings endpoint, loaded once and refreshed on save.
- The browser zone comes from `Intl.DateTimeFormat().resolvedOptions().timeZone`.

### D6. Mismatch test: equivalent over the next year, not equal names

Two zones match when they give the same UTC offset at every sample point across the next 12 months. The UI samples on the 1st and 15th of each month, using `Intl.DateTimeFormat` with `timeZoneName: "longOffset"`. Melbourne and Sydney, or `Australia/Brisbane` and its alias `Australia/Queensland`, then count as the same. Brisbane and Sydney differ during Sydney's DST and so count as a mismatch all year. Twice-monthly sampling can miss a DST period shorter than about two weeks, which no current zone has.

The dismissal is saved in `localStorage` under a key of the two zone names, inside try/catch. A different pair of zones brings the notice back. The notice is shown on the Updates & Backups section and in the cobble Settings card.

- *Alternative*: compare names. Rejected, because aliases and same-rule cities would show a notice that is wrong.
- *Alternative*: compare current offsets only. Rejected, because Brisbane against Sydney would look fine for half the year.

### D7. `tzdata` dependency

Add `tzdata` to `[project] dependencies`. `zoneinfo` prefers the system database and falls back to the `tzdata` package, so the release tarball's wheel install brings it in with no code change.

## Risks / Trade-offs

- [Existing installs on UTC hosts keep firing at UTC times until the operator sets a zone] → The mismatch notice appears on the Updates & Backups section the first time they open it from a browser in a different zone, with a one-click fix. The scheduled time does not move until the operator acts, so nothing changes without warning.
- [Setting a zone moves the next run without warning] → Saving shows the recomputed next runs straight away, because the status push refreshes them.
- [Consumers that parse `next_scheduled_at` as naive] → This is the only consumer-visible format change, and it is marked **BREAKING** in the proposal. The bundled UI is updated in the same change.
- [Host zone detection may give an offset rather than a name] → Schedules still work, because a fixed offset is a valid zone. The UI shows the offset, and the mismatch notice still fires.
- [`available_timezones()` includes legacy names such as `US/Pacific` and `Etc/GMT+10` (whose sign is inverted)] → Accepted, since they are valid. The picker could list canonical `Area/City` names first. That is a presentation detail and does not affect validation.

## Migration Plan

No data migration. On upgrade, `cobble_settings.json` does not exist, so the zone is unset, the host zone applies, and behaviour is the same as before. Rollback to an older cobble ignores the file. The only difference after a rollback is that `next_scheduled_at` is naive again.

## Open Questions

- Should the timezone select group or prioritise canonical `Area/City` names over legacy aliases? This is presentation only and can be settled during implementation.
