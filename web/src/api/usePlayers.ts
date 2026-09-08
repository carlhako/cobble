import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Roster } from "./client";
import { useStatus } from "./StatusContext";

export interface PlayersFeed {
  roster: Roster | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

// The roster is a plain fetch, kept live off the existing status stream: whenever
// the set of online players changes (a connect or a disconnect), it refetches,
// so the roster reflects arrivals and departures without a reload (task 7.5).
export function usePlayers(): PlayersFeed {
  const { status } = useStatus();
  const [roster, setRoster] = useState<Roster | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .players()
      .then((r) => {
        if (!cancelled) {
          setRoster(r);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  // A signature of who is online; changes drive a refetch.
  const onlineKey = (status?.online_players ?? [])
    .map((p) => p.xuid)
    .sort()
    .join(",");
  const prevKey = useRef<string | null>(null);
  useEffect(() => {
    if (prevKey.current !== null && prevKey.current !== onlineKey) reload();
    prevKey.current = onlineKey;
  }, [onlineKey, reload]);

  return { roster, loading, error, reload };
}
