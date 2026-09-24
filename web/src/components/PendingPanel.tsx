import { useState } from "react";
import { ApiCallError, api, type PendingChange } from "../api/client";

/** 7.5 / 7.6 — pending changes and the restart that applies them. Shared by the
 *  Configuration and Network sections, so both offer the same restart. */
export function PendingPanel({
  pending,
  running,
  onRestarted,
}: {
  pending: PendingChange[];
  running: boolean;
  onRestarted: () => void;
}) {
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [deferred, setDeferred] = useState(false);

  if (pending.length === 0) return null;

  const restart = async () => {
    setWorking(true);
    setErr(null);
    try {
      await api.restart();
      onRestarted();
    } catch (e) {
      setErr(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setWorking(false);
    }
  };

  return (
    <div
      className="panel is-warn"
      role="status"
      aria-label="pending configuration changes"
    >
      <strong>
        {pending.length} saved setting{pending.length === 1 ? "" : "s"} not yet in effect
      </strong>
      <p className="muted">
        The server reads its configuration only when it starts. These changes take effect
        the next time the server starts for any reason — an operator restart, a crash
        recovery, or an update.
      </p>
      <table className="cfg-pending">
        <thead>
          <tr>
            <th>Setting</th>
            <th>Saved</th>
            <th>In effect</th>
          </tr>
        </thead>
        <tbody>
          {pending.map((c) => (
            <tr key={c.key}>
              <td>{c.key}</td>
              <td>{c.saved ?? "(unset)"}</td>
              <td>{c.in_effect ?? "(unset)"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {running && !deferred && (
        <div className="controls-row">
          <button className="btn btn-restart" disabled={working} onClick={restart}>
            {working ? "Restarting…" : "Restart now to apply"}
          </button>
          <button className="btn" disabled={working} onClick={() => setDeferred(true)}>
            Later
          </button>
        </div>
      )}
      {running && deferred && (
        <p className="muted">
          Deferred. The changes will take effect the next time the server starts for any
          reason.
        </p>
      )}
      {err && <div className="controls-error">{err}</div>}
    </div>
  );
}
