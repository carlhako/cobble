import { useCallback, useState } from "react";
import { ApiCallError, api } from "./client";
import type { RunState } from "./client";

export type LifecycleAction = "start" | "stop" | "restart";

export interface LifecycleControls {
  busy: LifecycleAction | null;
  error: string | null;
  run: (action: LifecycleAction) => Promise<void>;
  clearError: () => void;
  /** Actions that make sense from the given run state. */
  available: (state: RunState | undefined) => LifecycleAction[];
}

export function useLifecycle(): LifecycleControls {
  const [busy, setBusy] = useState<LifecycleAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (action: LifecycleAction) => {
    setBusy(action);
    setError(null);
    try {
      await api[action]();
    } catch (e) {
      const msg = e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e);
      setError(msg);
    } finally {
      setBusy(null);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  const available = useCallback((state: RunState | undefined): LifecycleAction[] => {
    switch (state) {
      case "running":
        return ["stop", "restart"];
      case "stopped":
      case "crashed":
      case "failed":
      case "recovery_abandoned":
        return ["start"];
      case "starting":
      case "stopping":
        return []; // a transition is in progress; offer nothing conflicting
      default:
        return [];
    }
  }, []);

  return { busy, error, run, clearError, available };
}
