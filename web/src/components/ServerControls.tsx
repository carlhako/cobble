import { useLifecycle } from "../api/useLifecycle";
import type { RunState } from "../api/client";

const LABELS: Record<string, string> = {
  start: "Start",
  stop: "Stop",
  restart: "Restart",
};

// Offers only the actions valid for the current run state, shows a transition in
// progress, and reports a failed action with its reason (web-ui-shell:
// "Server control is available from the interface").
export function ServerControls({
  runState,
  disabled,
}: {
  runState: RunState | undefined;
  disabled?: boolean;
}) {
  const { busy, error, run, clearError, available } = useLifecycle();
  const actions = available(runState);
  const transitioning = runState === "starting" || runState === "stopping";

  return (
    <div className="controls">
      <div className="controls-row">
        {actions.map((a) => (
          <button
            key={a}
            className={`btn btn-${a}`}
            disabled={disabled || busy !== null}
            onClick={() => run(a)}
          >
            {busy === a ? `${LABELS[a]}…` : LABELS[a]}
          </button>
        ))}
        {(transitioning || busy) && (
          <span className="controls-status" role="status">
            {busy ? `${LABELS[busy]} requested…` : `${runState}…`}
          </span>
        )}
        {actions.length === 0 && !transitioning && (
          <span className="muted">No actions available</span>
        )}
      </div>
      {error && (
        <div className="controls-error" role="alert">
          Action failed: {error}
          <button className="link" onClick={clearError}>
            dismiss
          </button>
        </div>
      )}
    </div>
  );
}
