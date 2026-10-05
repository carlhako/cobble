import { useCallback, useEffect, useRef, useState } from "react";

export const RESTART_POLL_MS = 1500;

/** After a restore, cobble restarts its own process so it runs on the restored
 *  state (import-backup-archive design.md D7). This follows that restart the
 *  same way the self-upgrade does: watch `/health` until cobble has gone away
 *  and come back, then reload the page onto the restarted cobble. "Back" only
 *  counts after "away" was seen, so the old process answering in the second
 *  before it exits is not mistaken for the new one. */
export function useCobbleRestart(): { restarting: boolean; begin: () => void } {
  const [restarting, setRestarting] = useState(false);
  const wentAway = useRef(false);

  const begin = useCallback(() => {
    wentAway.current = false;
    setRestarting(true);
  }, []);

  useEffect(() => {
    if (!restarting) return;
    const id = window.setInterval(() => {
      void (async () => {
        try {
          const resp = await fetch("/health", { cache: "no-store" });
          if (!resp.ok) throw new Error(`http ${resp.status}`);
          if (wentAway.current) window.location.reload();
        } catch {
          wentAway.current = true; // cobble is restarting
        }
      })();
    }, RESTART_POLL_MS);
    return () => window.clearInterval(id);
  }, [restarting]);

  return { restarting, begin };
}

export function RestartingPanel({ what }: { what: string }) {
  return (
    <div className="panel is-busy" role="status" aria-label="cobble restarting">
      <strong>Cobble is restarting to load {what}.</strong>
      <div className="muted">
        This page reloads by itself once cobble is back; the server returns to the state
        it was in before.
      </div>
    </div>
  );
}
