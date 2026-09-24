import { useState } from "react";
import { useStatus } from "../api/StatusContext";
import { ApiCallError, api, type TransportView } from "../api/client";

/** Warns when the server is not on the transport its Bedrock version ships as
 *  the default: current clients may not see or reach it (BDS 1.26.51.1 made
 *  nethernet the default and only supported transport). Offers the switch, and
 *  on the dashboard the restart that applies it. The Configuration page has its
 *  own pending-changes panel for the restart, so it passes `showRestart={false}`. */
export function TransportNotice({
  view,
  onChanged,
  showRestart = true,
}: {
  view: TransportView | null;
  onChanged: () => void | Promise<void>;
  showRestart?: boolean;
}) {
  const { status, stale } = useStatus();
  const [busy, setBusy] = useState<null | "switch" | "restart">(null);
  const [err, setErr] = useState<string | null>(null);

  if (!view || view.is_recommended || !view.recommended || !view.value) return null;
  const recommended = view.recommended;
  const blocked = stale || !!status?.maintenance || busy !== null;

  const act = async (kind: "switch" | "restart") => {
    setBusy(kind);
    setErr(null);
    try {
      if (kind === "switch") {
        const res = await api.configWrite({ transport: recommended });
        if (!res.ok) throw new Error(res.errors.map((e) => e.message).join("; "));
      } else {
        await api.restart();
      }
      await onChanged();
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const switched = view.pending_restart && view.saved === recommended;
  // The saved value is what the next start uses; name it when it is the problem.
  const offending = view.saved !== recommended ? view.saved : view.value;
  return (
    <div className="panel is-warn transport-notice" role="status">
      {switched ? (
        <>
          <strong>Switched to {recommended}.</strong> The server is still running{" "}
          {view.value} until it restarts.
          {showRestart && (
            <div className="controls-row">
              <button
                className="btn"
                disabled={blocked}
                onClick={() => void act("restart")}
              >
                {busy === "restart" ? "Restarting…" : "Restart now"}
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          <strong>{offending} is not the recommended transport.</strong> Bedrock{" "}
          {status?.version ?? ""} uses {recommended} by default. Players may not be able
          to see or join the server.
          <div className="controls-row">
            <button className="btn" disabled={blocked} onClick={() => void act("switch")}>
              {busy === "switch" ? "Switching…" : `Switch to ${recommended}`}
            </button>
          </div>
        </>
      )}
      {err && <div className="controls-error">{err}</div>}
    </div>
  );
}
