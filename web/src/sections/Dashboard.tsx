import { useEffect, useRef, useState } from "react";
import { useStatus } from "../api/StatusContext";
import { ServerControls } from "../components/ServerControls";
import { ApiCallError, api, type RunState } from "../api/client";

const STATE_LABEL: Record<RunState, string> = {
  stopped: "Stopped",
  starting: "Starting",
  running: "Running",
  stopping: "Stopping",
  crashed: "Crashed",
  failed: "Failed to start",
  recovery_abandoned: "Recovery abandoned",
};

function formatUptime(seconds: number | null): string {
  if (seconds == null) return "—";
  const s = Math.floor(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const parts = [d && `${d}d`, h && `${h}h`, m && `${m}m`, `${s % 60}s`].filter(Boolean);
  return parts.join(" ");
}

/** Interpolate uptime between server frames so it counts up once a second
 *  without needing a push for every tick. */
function useLiveUptime(base: number | null, running: boolean): number | null {
  const anchor = useRef<{ base: number; at: number } | null>(null);
  const [, force] = useState(0);

  if (base == null || !running) {
    anchor.current = null;
  } else if (anchor.current === null || Math.abs(anchor.current.base - base) > 2) {
    anchor.current = { base, at: Date.now() };
  }

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  if (anchor.current === null) return null;
  return anchor.current.base + (Date.now() - anchor.current.at) / 1000;
}

function BootstrapNotice({ state, detail }: { state: string; detail: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const retry = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.bootstrap();
    } catch (e) {
      setError(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (state === "running") {
    return (
      <div className="panel bootstrap-notice" role="status">
        <strong>Installing the Bedrock server…</strong>
        <span className="muted">
          {" "}
          {detail || "downloading — this can take a few minutes"}
        </span>
      </div>
    );
  }
  if (state === "failed") {
    return (
      <div className="panel bootstrap-notice is-error" role="alert">
        <strong>Bedrock server install failed.</strong>
        <span className="muted"> {detail}</span>
        <div>
          <button className="btn btn-start" disabled={busy} onClick={retry}>
            {busy ? "Retrying…" : "Retry install"}
          </button>
          {error && <span className="controls-error"> {error}</span>}
        </div>
      </div>
    );
  }
  return null;
}

export function Dashboard() {
  const { status, stale } = useStatus();
  const run = status?.run_state;
  const uptime = useLiveUptime(status?.uptime_seconds ?? null, run === "running");
  const bootstrapping = status?.bootstrap === "running";

  return (
    <section className={`section dashboard${stale ? " is-stale" : ""}`}>
      <h1>Dashboard</h1>

      {status && (
        <BootstrapNotice state={status.bootstrap} detail={status.bootstrap_detail} />
      )}

      <div className="cards">
        <div className="card">
          <div className="card-label">Server</div>
          <div className={`card-value state-${run ?? "unknown"}`}>
            {run ? STATE_LABEL[run] : "…"}
          </div>
        </div>
        <div className="card">
          <div className="card-label">Version</div>
          <div className="card-value">{status?.version ?? "not installed"}</div>
        </div>
        <div className="card">
          <div className="card-label">Uptime</div>
          <div className="card-value">{formatUptime(uptime)}</div>
        </div>
        <div className="card">
          <div className="card-label">Players online</div>
          <div className="card-value">
            {status ? status.online_players.length : "—"}
            {status?.players_incomplete && (
              <span className="badge" title="cobble could not observe the full session">
                may be incomplete
              </span>
            )}
          </div>
        </div>
      </div>

      <ServerControls runState={run} disabled={stale || bootstrapping} />

      <div className="panel">
        <h2>Online players</h2>
        {status && status.online_players.length > 0 ? (
          <ul className="player-list">
            {status.online_players.map((p) => (
              <li key={p.xuid}>
                <span className="gamertag">{p.gamertag || "(unknown)"}</span>
                <span className="xuid">{p.xuid}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">No one is online.</p>
        )}
      </div>

      {status?.last_crash && (
        <div className="panel">
          <h2>Last crash</h2>
          <p className={status.last_crash.recovery === "abandoned" ? "warn" : "ok"}>
            {status.last_crash.recovery === "running" && "Auto-restarted and running"}
            {status.last_crash.recovery === "restarting" && "Crashed — restarting…"}
            {status.last_crash.recovery === "abandoned" &&
              "Recovery abandoned after repeated crashes"}
            {(status.last_crash.recovery === "stopped" ||
              status.last_crash.recovery === "none") &&
              "Crashed"}
            <span className="muted">
              {" "}
              · exit code {status.last_crash.exit_code ?? "?"} ·{" "}
              {new Date(status.last_crash.at).toLocaleString()}
            </span>
          </p>
        </div>
      )}

      <div className="panel">
        <h2>Last shutdown</h2>
        {status?.last_shutdown ? (
          <p className={status.last_shutdown.clean ? "ok" : "warn"}>
            {status.last_shutdown.clean
              ? "Clean"
              : "Unclean — server was forcibly terminated"}
            <span className="muted">
              {" "}
              · {new Date(status.last_shutdown.at).toLocaleString()}
            </span>
          </p>
        ) : (
          <p className="muted">No shutdown recorded yet.</p>
        )}
      </div>
    </section>
  );
}
