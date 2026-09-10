import { useCallback, useEffect, useRef, useState } from "react";
import { api, type PlayerSessions } from "./client";
import { useStatus } from "./StatusContext";

export interface PlayerSessionsFeed {
  sessions: PlayerSessions | null;
  error: string | null;
  reload: () => void;
}

// The selected player's session history is a plain fetch, kept live off the
// existing status stream. A moderation action or an observed departure closes a
// session server-side moments after the action itself returns, and that surfaces
// as a change to the online set or the recorded ban count — the same signals the
// roster and access views refetch on. Refetching here keeps a displayed session
// from showing "in progress" after it has been closed, without a page reload
// (web-ui-shell: a displayed session that ends is reflected without reloading).
export function usePlayerSessions(xuid: string | null): PlayerSessionsFeed {
  const { status } = useStatus();
  const [sessions, setSessions] = useState<PlayerSessions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  // Clear on a player change; keep the last data on a reload-driven refetch so
  // the panel does not flash back to a loading state on every status tick.
  const shownXuid = useRef<string | null>(null);
  useEffect(() => {
    const changedPlayer = shownXuid.current !== xuid;
    shownXuid.current = xuid;
    if (xuid === null) {
      setSessions(null);
      setError(null);
      return;
    }
    let cancelled = false;
    if (changedPlayer) {
      setSessions(null);
      setError(null);
    }
    api
      .playerSessions(xuid)
      .then((d) => {
        if (!cancelled) {
          setSessions(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [xuid, tick]);

  // A signature of the signals that can close a session out from under the
  // panel: who is online, and the standing access posture (the ban count).
  const signalKey =
    (status?.online_players ?? [])
      .map((p) => p.xuid)
      .sort()
      .join(",") +
    "|" +
    JSON.stringify(status?.access ?? null);
  const prevKey = useRef<string | null>(null);
  useEffect(() => {
    if (prevKey.current !== null && prevKey.current !== signalKey) reload();
    prevKey.current = signalKey;
  }, [signalKey, reload]);

  return { sessions, error, reload };
}
