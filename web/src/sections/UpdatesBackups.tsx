import { useCallback, useEffect, useState } from "react";
import { useStatus } from "../api/StatusContext";
import {
  ApiCallError,
  api,
  type BackupEntry,
  type UpdateDiagnostics,
} from "../api/client";

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
      <BackupsPanel busy={busy} />
    </section>
  );
}
