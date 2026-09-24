import { useCallback, useEffect, useState } from "react";
import { useStatus } from "../api/StatusContext";
import { useCobbleVersion } from "../api/useCobbleVersion";
import {
  ApiCallError,
  api,
  type BackupEntry,
  type BackupHistoryEntry,
  type CobbleVersion,
  type MaintenanceSettings,
  type ScheduleConfig,
  type ScheduleFrequency,
  type UpdateDiagnostics,
  type VersionHistoryEntry,
} from "../api/client";

const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** 10.7 — a maintenance operation in progress, with its current step. */
function MaintenanceBanner() {
  const { status } = useStatus();
  const m = status?.maintenance;
  if (!m) return null;
  const label =
    m.operation === "updating"
      ? "Update in progress"
      : m.operation === "restoring"
        ? "Restore in progress"
        : m.operation === "cobble_upgrade"
          ? "cobble upgrade in progress"
          : "Backup in progress";
  return (
    <div className="panel is-busy" role="status">
      <strong>{label}</strong>
      {m.step && <span className="muted"> · {m.step}</span>}
      <div className="muted">
        Lifecycle and maintenance controls are unavailable until it finishes.
      </div>
    </div>
  );
}

/** 10.3 — a failed update, with the version attempted, failing step, and the
 *  server output captured during the attempt. */
function FailedUpdateAlert() {
  const { status } = useStatus();
  const result = status?.update?.last_result;
  const failed =
    result && (result.status === "rolled_back" || result.status === "aborted");
  const [diag, setDiag] = useState<UpdateDiagnostics | null>(null);
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setDiag(null);
    setOpen(false);
  }, [result?.at]);

  if (!failed) return null;

  const showOutput = async () => {
    setErr(null);
    try {
      const { diagnostics } = await api.updatesDiagnostics();
      setDiag(diagnostics);
      setOpen(true);
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
    }
  };

  return (
    <div className="panel is-error" role="alert">
      <strong>
        {result.status === "rolled_back"
          ? "The last update failed and was rolled back."
          : "The last update was abandoned."}
      </strong>
      <div className="muted">
        Attempted {result.to_version ?? "?"}
        {result.step && ` · failed at the "${result.step}" step`} · {fmtTime(result.at)}
      </div>
      <p>{result.detail}</p>
      <button className="btn" onClick={showOutput}>
        {open ? "Refresh captured output" : "Show captured output"}
      </button>
      {err && <span className="controls-error"> {err}</span>}
      {open && (
        <pre className="diag-output" aria-label="captured update output">
          {diag?.output || "(no output captured)"}
        </pre>
      )}
    </div>
  );
}

/** 10.5 — rollback could not restore service. Visually distinct from an
 *  ordinary failed update; needs operator intervention. */
function RollbackFailedAlert() {
  const { status } = useStatus();
  if (!status?.update?.terminal) return null;
  return (
    <div className="panel is-critical" role="alert">
      <strong>Automatic recovery has stopped — operator intervention required.</strong>
      <p>
        A rollback could not start the previous version. cobble has made no further
        automatic changes. Restore a backup or repair the installation on the host, then
        clear the failed-version record below.
      </p>
    </div>
  );
}

/** 10.2 + 10.4 — version state, a check action, and the skipped-version notice. */
function VersionPanel({ busy }: { busy: boolean }) {
  const { status } = useStatus();
  const v = status?.version_info;
  const u = status?.update;
  const [working, setWorking] = useState<null | "check" | "apply" | "clear">(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async (
    kind: "check" | "apply" | "clear",
    fn: () => Promise<unknown>,
    ok: (r: unknown) => string,
  ) => {
    setWorking(kind);
    setMsg(null);
    setErr(null);
    try {
      setMsg(ok(await fn()));
    } catch (e) {
      setErr(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setWorking(null);
    }
  };

  const pending = v && v.available && v.up_to_date === false && !u?.skipping;

  return (
    <div className="panel">
      <h2>Version</h2>
      <div className="cards">
        <div className="card">
          <div className="card-label">Installed</div>
          <div className="card-value">{v?.installed ?? "—"}</div>
        </div>
        <div className="card">
          <div className="card-label">Available</div>
          <div className="card-value">{v?.available ?? "unknown"}</div>
        </div>
        <div className="card">
          <div className="card-label">Status</div>
          <div className="card-value">
            {v?.up_to_date === true && "Up to date"}
            {pending && "Update pending"}
            {u?.skipping && "Update held"}
            {v?.up_to_date == null && !u?.skipping && "Not checked"}
          </div>
        </div>
      </div>

      <div className="muted">
        Last checked {fmtTime(u?.last_check_at ?? null)} · next scheduled{" "}
        {fmtTime(u?.next_scheduled_at ?? null)}
      </div>

      {u?.skipping && (
        <div className="panel is-warn" role="status">
          Version {u.skipping} previously failed an update and will not be retried
          automatically.{" "}
          <button
            className="btn"
            disabled={busy || working !== null}
            onClick={() =>
              run(
                "clear",
                () => api.updatesClearFailed(u.skipping ?? undefined),
                () => `Cleared — ${u.skipping} may be attempted again.`,
              )
            }
          >
            {working === "clear" ? "Clearing…" : "Clear record"}
          </button>
        </div>
      )}

      <div className="controls-row">
        <button
          className="btn"
          disabled={busy || working !== null}
          onClick={() =>
            run(
              "check",
              () => api.updatesCheck(),
              (r) => {
                const c = r as {
                  available: string | null;
                  up_to_date: boolean;
                  error: string | null;
                };
                if (c.error) return `Check failed: ${c.error}`;
                if (c.up_to_date) return "Already up to date.";
                return c.available ? `Update available: ${c.available}` : "Checked.";
              },
            )
          }
        >
          {working === "check" ? "Checking…" : "Check for updates"}
        </button>
        {pending && (
          <button
            className="btn btn-start"
            disabled={busy || working !== null}
            onClick={() =>
              run(
                "apply",
                () => api.updatesApply(),
                (r) => {
                  const res = r as { status: string; detail: string };
                  return res.detail;
                },
              )
            }
          >
            {working === "apply" ? "Updating…" : `Update to ${v?.available}`}
          </button>
        )}
      </div>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="controls-error">{err}</div>}
    </div>
  );
}

/** Backup history tab: every successful capture ever recorded, independent of
 *  whether the archive itself has since been pruned. */
function BackupHistoryTab() {
  const [items, setItems] = useState<BackupHistoryEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { history } = await api.backupsHistory();
        if (!cancelled) setItems(history ?? []);
      } catch (e) {
        if (!cancelled) setErr(e instanceof ApiCallError ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (err) return <div className="controls-error">{err}</div>;
  if (items === null) return <p className="muted">Loading…</p>;
  if (items.length === 0) return <p className="muted">No backups recorded yet.</p>;

  return (
    <table className="backup-list">
      <thead>
        <tr>
          <th>Captured</th>
          <th>Version</th>
          <th>Size</th>
          <th>Trigger</th>
          <th>Archive</th>
        </tr>
      </thead>
      <tbody>
        {items.map((h, i) => (
          <tr key={`${h.archive}-${i}`} className={h.still_held ? "" : "is-unusable"}>
            <td>{fmtTime(h.at)}</td>
            <td>{h.bedrock_version ?? "—"}</td>
            <td>{fmtBytes(h.size_bytes)}</td>
            <td>{h.reason}</td>
            <td>{h.still_held ? "Held" : "Pruned"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Version history tab: every successful update ever applied. */
function VersionHistoryTab() {
  const [items, setItems] = useState<VersionHistoryEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { history } = await api.updatesHistory();
        if (!cancelled) setItems(history ?? []);
      } catch (e) {
        if (!cancelled) setErr(e instanceof ApiCallError ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (err) return <div className="controls-error">{err}</div>;
  if (items === null) return <p className="muted">Loading…</p>;
  if (items.length === 0) return <p className="muted">No updates recorded yet.</p>;

  return (
    <table className="backup-list">
      <thead>
        <tr>
          <th>Installed</th>
          <th>From</th>
          <th>To</th>
          <th>Trigger</th>
        </tr>
      </thead>
      <tbody>
        {items.map((h, i) => (
          <tr key={`${h.at}-${i}`}>
            <td>{fmtTime(h.at)}</td>
            <td>{h.from_version ?? "—"}</td>
            <td>
              {h.to_version ?? "—"}
              {h.settings_changed && h.settings_changed.length > 0 && (
                <div className="muted settings-changed">
                  New Bedrock defaults:{" "}
                  {h.settings_changed
                    .map((c) => `${c.key} ${c.from} → ${c.to}`)
                    .join(", ")}
                </div>
              )}
            </td>
            <td>{h.trigger}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One time + frequency + conditional day editor, shared by the backup and
 *  update-check schedules. */
function ScheduleEditor({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: ScheduleConfig;
  onChange: (next: ScheduleConfig) => void;
  disabled: boolean;
}) {
  const setFrequency = (frequency: ScheduleFrequency) => {
    const day = frequency === "weekly" ? 0 : frequency === "monthly" ? 1 : null;
    onChange({ ...value, frequency, day });
  };

  return (
    <fieldset className="schedule-editor" disabled={disabled}>
      <legend>{label}</legend>
      <label>
        Time{" "}
        <input
          type="time"
          value={value.time}
          onChange={(e) => onChange({ ...value, time: e.target.value })}
        />
      </label>
      <label>
        Frequency{" "}
        <select
          value={value.frequency}
          onChange={(e) => setFrequency(e.target.value as ScheduleFrequency)}
        >
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
        </select>
      </label>
      {value.frequency === "weekly" && (
        <label>
          Day{" "}
          <select
            value={value.day ?? 0}
            onChange={(e) => onChange({ ...value, day: Number(e.target.value) })}
          >
            {WEEKDAYS.map((name, idx) => (
              <option key={name} value={idx}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
      {value.frequency === "monthly" && (
        <label>
          Day of month{" "}
          <input
            type="number"
            min={1}
            max={31}
            value={value.day ?? 1}
            onChange={(e) => onChange({ ...value, day: Number(e.target.value) })}
          />
        </label>
      )}
    </fieldset>
  );
}

/** Settings tab: retention, scheduled-backups on/off, the two schedule
 *  editors, and the pre-update backup's fixed informational note (no control —
 *  maintenance-settings spec: "not exposed as a toggle"). */
function SettingsTab() {
  const [settings, setSettings] = useState<MaintenanceSettings | null>(null);
  const [draft, setDraft] = useState<MaintenanceSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.maintenanceSettingsRead();
      setSettings(s);
      setDraft(s);
    } catch (e) {
      setErrors([e instanceof ApiCallError ? e.message : String(e)]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (errors.length && !settings)
    return <div className="controls-error">{errors[0]}</div>;
  if (!draft) return <p className="muted">Loading…</p>;

  const save = async () => {
    setSaving(true);
    setErrors([]);
    setMsg(null);
    try {
      const result = await api.maintenanceSettingsWrite({
        backup_retention: draft.backup_retention,
        backup_enabled: draft.backup_enabled,
        backup_schedule: draft.backup_schedule,
        update_schedule: draft.update_schedule,
      });
      if (!result.ok) {
        setErrors(result.errors);
      } else if (result.settings) {
        setSettings(result.settings);
        setDraft(result.settings);
        setMsg("Settings saved.");
      }
    } catch (e) {
      setErrors([e instanceof ApiCallError ? e.message : String(e)]);
    } finally {
      setSaving(false);
    }
  };

  const dirty = settings !== null && JSON.stringify(settings) !== JSON.stringify(draft);

  return (
    <div className="settings-tab">
      <label className="controls-row">
        <input
          type="number"
          min={1}
          value={draft.backup_retention}
          onChange={(e) =>
            setDraft({ ...draft, backup_retention: Number(e.target.value) })
          }
          aria-label="Backup retention"
          style={{ width: "5rem" }}
        />
        <span>backups retained</span>
      </label>

      <label className="controls-row">
        <input
          type="checkbox"
          checked={draft.backup_enabled}
          onChange={(e) => setDraft({ ...draft, backup_enabled: e.target.checked })}
        />
        <span>Scheduled backups enabled</span>
      </label>

      <p className="muted">
        A verified backup is always captured automatically before an update is applied.
        This safety step cannot be disabled.
      </p>

      <ScheduleEditor
        label="Backup schedule"
        value={draft.backup_schedule}
        disabled={!draft.backup_enabled}
        onChange={(backup_schedule) => setDraft({ ...draft, backup_schedule })}
      />
      <label className="controls-row">
        <input
          type="checkbox"
          checked={draft.update_schedule.enabled}
          onChange={(e) =>
            setDraft({
              ...draft,
              update_schedule: { ...draft.update_schedule, enabled: e.target.checked },
            })
          }
        />
        <span>Scheduled update checks enabled</span>
      </label>
      <ScheduleEditor
        label="Update-check schedule"
        value={draft.update_schedule}
        disabled={!draft.update_schedule.enabled}
        onChange={(update_schedule) => setDraft({ ...draft, update_schedule })}
      />

      <div className="controls-row">
        <button className="btn" disabled={saving || !dirty} onClick={() => void save()}>
          {saving ? "Saving…" : "Save settings"}
        </button>
        {dirty && (
          <button className="link" disabled={saving} onClick={() => setDraft(settings)}>
            revert
          </button>
        )}
      </div>
      {msg && <div className="ok">{msg}</div>}
      {errors.map((e) => (
        <div key={e} className="controls-error">
          {e}
        </div>
      ))}
    </div>
  );
}

/** cobble's own version and one-click upgrade (cobble-self-update; web-ui-shell:
 *  "Cobble upgrades are available from the settings screen"). Distinct from the
 *  Bedrock server's version panel above. */
function CobbleCard() {
  const { status, stale } = useStatus();
  const { info, set } = useCobbleVersion();
  const [working, setWorking] = useState<null | "check" | "upgrade">(null);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const heading = <h3>cobble (control panel)</h3>;
  if (!info)
    return (
      <div className="cobble-card">
        {heading}
        <p className="muted">Loading…</p>
      </div>
    );

  const u = info.upgrade;
  const inFlight = u?.state === "pending" || u?.state === "running";
  const busy = stale || !!status?.maintenance || inFlight;

  const call = async (kind: "check" | "upgrade", fn: () => Promise<CobbleVersion>) => {
    setWorking(kind);
    setErr(null);
    try {
      set(await fn());
      setConfirm(false);
    } catch (e) {
      setErr(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setWorking(null);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(info.manual_command ?? "");
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="cobble-card">
      {heading}
      <div className="cards">
        <div className="card">
          <div className="card-label">Installed</div>
          <div className="card-value">{info.current}</div>
        </div>
        <div className="card">
          <div className="card-label">Latest release</div>
          <div className="card-value">{info.latest ?? "unknown"}</div>
        </div>
        <div className="card">
          <div className="card-label">Status</div>
          <div className="card-value">
            {inFlight
              ? "Upgrading"
              : info.update_available
                ? "Update available"
                : info.latest
                  ? "Up to date"
                  : "Not checked"}
          </div>
        </div>
      </div>
      <div className="muted">
        Last checked {fmtTime(info.checked_at)}
        {info.release_url && (
          <>
            {" · "}
            <a href={info.release_url} target="_blank" rel="noopener noreferrer">
              release notes
            </a>
          </>
        )}
      </div>
      {info.check_error && (
        <div className="muted">
          The last check could not reach GitHub: {info.check_error}
        </div>
      )}

      <div className="controls-row">
        <button
          className="btn"
          disabled={working !== null}
          onClick={() => void call("check", api.cobbleCheck)}
        >
          {working === "check" ? "Checking…" : "Check now"}
        </button>
        {info.update_available && info.one_click_available && info.latest && (
          <button
            className="btn"
            disabled={busy || working !== null}
            onClick={() => setConfirm(true)}
          >
            Upgrade to {info.latest}
          </button>
        )}
      </div>

      {info.update_available && !info.one_click_available && info.manual_command && (
        <div className="manual-upgrade">
          <p>
            This install predates one-click upgrades. To upgrade, run this as root on the
            container. Later upgrades can then be done from here.
          </p>
          <div className="controls-row">
            <code aria-label="manual upgrade command">{info.manual_command}</code>
            <button className="btn" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}

      {confirm && info.latest && (
        <div
          className="panel is-warn"
          role="alertdialog"
          aria-label="confirm cobble upgrade"
        >
          <strong>Upgrade cobble to {info.latest}?</strong>
          <p className="warn">
            The Bedrock server will be stopped and players disconnected. cobble takes a
            verified backup, installs {info.latest}, and restarts. The server comes back
            once the new cobble has started, and this page reloads by itself.
          </p>
          <div className="controls-row">
            <button
              className="btn btn-stop"
              disabled={busy || working !== null}
              onClick={() =>
                void call("upgrade", () => api.cobbleUpgrade(info.latest ?? ""))
              }
            >
              {working === "upgrade" ? "Backing up…" : "Back up and upgrade"}
            </button>
            <button
              className="btn"
              disabled={working !== null}
              onClick={() => setConfirm(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {err && <div className="controls-error">{err}</div>}

      {inFlight && u && (
        <div className="muted" role="status">
          Upgrade to {u.to}{" "}
          {u.state === "running" ? "is installing" : "is waiting for the helper"}…
        </div>
      )}
      {u && !inFlight && (
        <div className={u.state === "succeeded" ? "ok" : "warn"} role="status">
          Last upgrade: {u.from ?? "?"} → {u.to ?? "?"},{" "}
          {u.state === "succeeded" ? "succeeded" : u.state} {fmtTime(u.finished_at)}
          {u.error && <div>{u.error}</div>}
        </div>
      )}
      {u && !inFlight && u.state !== "succeeded" && u.log_tail && (
        <pre className="diag-output" aria-label="upgrade output">
          {u.log_tail}
        </pre>
      )}
    </div>
  );
}

type MaintenanceTab = "history" | "versions" | "settings";

/** Tabbed panel under the version panel: backup history, version history, and
 *  the live-editable maintenance settings (task 7.2). The existing live
 *  `BackupsPanel` (capture/restore/download) is untouched and unaffected. */
function MaintenanceTabsPanel() {
  const [tab, setTab] = useState<MaintenanceTab>("history");
  const tabs: { id: MaintenanceTab; label: string }[] = [
    { id: "history", label: "Backup history" },
    { id: "versions", label: "Version history" },
    { id: "settings", label: "Settings" },
  ];

  return (
    <div className="panel">
      <div className="tabs" role="tablist" aria-label="Maintenance">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`tab${tab === t.id ? " is-active" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "history" && <BackupHistoryTab />}
        {tab === "versions" && <VersionHistoryTab />}
        {tab === "settings" && (
          <>
            <CobbleCard />
            <SettingsTab />
          </>
        )}
      </div>
    </div>
  );
}

/** 10.6 + 10.8 — the backup list, a capture action, and a confirmed restore. */
function BackupsPanel({ busy }: { busy: boolean }) {
  const { status } = useStatus();
  const unhealthy = status?.backup?.unhealthy ?? null;
  const [items, setItems] = useState<BackupEntry[] | null>(null);
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<BackupEntry | null>(null);
  const [confirmOld, setConfirmOld] = useState<{
    entry: BackupEntry;
    warning: string;
  } | null>(null);

  const reload = useCallback(async () => {
    try {
      setItems((await api.backupsList()).backups);
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
    }
  }, []);

  // Reload on mount and whenever the backup summary changes (count / last / health).
  useEffect(() => {
    void reload();
  }, [reload, status?.backup?.last_at, status?.backup?.count, unhealthy]);

  const capture = async () => {
    setWorking(true);
    setErr(null);
    try {
      const r = await api.backupsCapture();
      if (!r.ok) setErr(r.error ?? "backup failed");
      await reload();
    } catch (e) {
      setErr(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setWorking(false);
    }
  };

  const doRestore = async (entry: BackupEntry, confirmOldVersion: boolean) => {
    setWorking(true);
    setErr(null);
    try {
      const r = await api.backupsRestore(entry.archive, confirmOldVersion);
      if (r.needs_confirmation && r.warning) {
        setConfirmOld({ entry, warning: r.warning });
      } else if (!r.ok) {
        setErr(r.error ?? "restore failed");
      }
      await reload();
    } catch (e) {
      setErr(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setWorking(false);
      setConfirm(null);
      setConfirmOld(null);
    }
  };

  return (
    <div className="panel">
      <h2>Backups</h2>

      {unhealthy && (
        <div className="panel is-error" role="alert">
          <strong>Backups are failing.</strong> <span className="muted">{unhealthy}</span>
        </div>
      )}

      <div className="controls-row">
        <button className="btn" disabled={busy || working} onClick={capture}>
          {working ? "Working…" : "Capture backup now"}
        </button>
        <button className="link" onClick={() => void reload()} disabled={working}>
          refresh
        </button>
      </div>
      {err && <div className="controls-error">{err}</div>}

      {items === null ? (
        <p className="muted">Loading…</p>
      ) : items.length === 0 ? (
        <p className="muted">No backups held.</p>
      ) : (
        <table className="backup-list">
          <thead>
            <tr>
              <th>Captured</th>
              <th>Version</th>
              <th>Size</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((b) => (
              <tr key={b.archive} className={b.restorable ? "" : "is-unusable"}>
                <td>{fmtTime(b.captured_at)}</td>
                <td>{b.bedrock_version ?? "—"}</td>
                <td>{fmtBytes(b.size_bytes)}</td>
                <td className="backup-actions">
                  <a className="btn" href={api.backupsDownloadUrl(b.archive)} download>
                    Download
                  </a>
                  {b.restorable ? (
                    <button
                      className="btn"
                      disabled={busy || working}
                      onClick={() => setConfirm(b)}
                    >
                      Restore
                    </button>
                  ) : (
                    <span className="muted" title={b.reason ?? undefined}>
                      not restorable
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {confirm && (
        <div
          className="panel is-warn confirm-restore"
          role="alertdialog"
          aria-label="confirm restore"
        >
          <strong>Restore this backup?</strong>
          <p>
            Backup <code>{confirm.archive}</code>, captured {fmtTime(confirm.captured_at)}
            {confirm.bedrock_version && ` under Bedrock ${confirm.bedrock_version}`}.
          </p>
          <p className="warn">
            This replaces the current world and cobble state. The state being replaced is
            captured first, but current progress since that state will be lost.
          </p>
          <div className="controls-row">
            <button
              className="btn btn-stop"
              disabled={working}
              onClick={() => void doRestore(confirm, false)}
            >
              {working ? "Restoring…" : "Replace current state and restore"}
            </button>
            <button className="btn" disabled={working} onClick={() => setConfirm(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {confirmOld && (
        <div
          className="panel is-warn confirm-restore"
          role="alertdialog"
          aria-label="confirm older-version restore"
        >
          <strong>This backup is older than the installed server.</strong>
          <p>{confirmOld.warning}</p>
          <div className="controls-row">
            <button
              className="btn btn-stop"
              disabled={working}
              onClick={() => void doRestore(confirmOld.entry, true)}
            >
              Restore anyway
            </button>
            <button
              className="btn"
              disabled={working}
              onClick={() => setConfirmOld(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function UpdatesBackups() {
  const { status, stale } = useStatus();
  const maintenanceActive = !!status?.maintenance;
  const busy = stale || maintenanceActive;

  return (
    <section className={`section updates-backups${stale ? " is-stale" : ""}`}>
      <h1>Updates &amp; Backups</h1>
      <MaintenanceBanner />
      <RollbackFailedAlert />
      <FailedUpdateAlert />
      <VersionPanel busy={busy} />
      <MaintenanceTabsPanel />
      <BackupsPanel busy={busy} />
    </section>
  );
}
