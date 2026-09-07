import { useCallback, useRef, useState } from "react";
import { useEventSource } from "./useEventSource";
import { api } from "./client";

export interface ConsoleLine {
  seq: number;
  kind: "output" | "command" | "marker";
  text: string;
}

const MAX_LINES = 5000;

export interface ConsoleFeed {
  lines: ConsoleLine[];
  connected: boolean;
  send: (command: string) => Promise<void>;
}

// Streams console output, keeping a bounded scroll-back buffer, de-duplicated by
// sequence number so a reconnect (which replays retained history) does not
// double up lines already shown.
export function useConsole(): ConsoleFeed {
  const [lines, setLines] = useState<ConsoleLine[]>([]);
  const lastSeq = useRef(0);

  const onMessage = useCallback((ev: MessageEvent) => {
    let line: ConsoleLine;
    try {
      line = JSON.parse(ev.data) as ConsoleLine;
    } catch {
      return;
    }
    if (line.seq <= lastSeq.current) return;
    lastSeq.current = line.seq;
    setLines((prev) => {
      const next = prev.concat(line);
      return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
    });
  }, []);

  const { connected } = useEventSource("/api/console/stream", onMessage);

  const send = useCallback((command: string) => api.sendCommand(command), []);

  return { lines, connected, send };
}
