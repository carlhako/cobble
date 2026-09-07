import { useEffect, useRef, useState } from "react";

export interface EventSourceState {
  connected: boolean;
}

// Wraps EventSource with automatic reconnection and a `connected` flag the shell
// uses to show a disconnected banner and avoid presenting stale state as current
// (web-ui-shell: "The interface recovers from lost connections").
export function useEventSource(
  url: string,
  onMessage: (ev: MessageEvent) => void,
): EventSourceState {
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;

  useEffect(() => {
    let es: EventSource | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      es = new EventSource(url);
      es.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      es.onmessage = (ev) => handlerRef.current(ev);
      es.onerror = () => {
        setConnected(false);
        es?.close();
        es = null;
        const delay = Math.min(1000 * 2 ** retry, 15000);
        retry += 1;
        timer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [url]);

  return { connected };
}
