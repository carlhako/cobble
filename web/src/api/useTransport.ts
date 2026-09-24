import { useCallback, useEffect, useState } from "react";
import { useStatus } from "./StatusContext";
import { api, type TransportView } from "./client";

/** The transport view, refreshed whenever the server's run state or its pending
 *  configuration changes (a save, a start, a restart), which the status stream
 *  already pushes. */
export function useTransport(): {
  view: TransportView | null;
  refresh: () => Promise<void>;
} {
  const { status } = useStatus();
  const [view, setView] = useState<TransportView | null>(null);

  const refresh = useCallback(async () => {
    try {
      setView(await api.configTransport());
    } catch {
      // Unknown until the next change; the card shows a dash meanwhile.
    }
  }, []);

  const runState = status?.run_state;
  const pendingCount = status?.config?.pending_count ?? 0;
  const version = status?.version;
  useEffect(() => {
    void refresh();
  }, [refresh, runState, pendingCount, version]);

  return { view, refresh };
}
