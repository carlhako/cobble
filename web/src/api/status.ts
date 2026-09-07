import { useCallback, useRef, useState } from "react";
import { useEventSource } from "./useEventSource";
import type { StatusPayload } from "./client";

export interface ServerStatus {
  status: StatusPayload | null;
  connected: boolean;
  /** True when we have a status but the live connection is currently down, so
   *  it must not be presented as authoritative (web-ui-shell). */
  stale: boolean;
}

// Subscribes to the status SSE stream. On (re)connect the server replays the
// current status, so `status` is brought up to date automatically after a
// dropped connection.
export function useServerStatus(): ServerStatus {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const hadStatus = useRef(false);

  const onMessage = useCallback((ev: MessageEvent) => {
    try {
      setStatus(JSON.parse(ev.data) as StatusPayload);
      hadStatus.current = true;
    } catch {
      // ignore malformed frame
    }
  }, []);

  const { connected } = useEventSource("/api/status/stream", onMessage);
  return { status, connected, stale: hadStatus.current && !connected };
}
