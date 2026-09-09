import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AccessRead } from "./client";
import { useStatus } from "./StatusContext";

export interface AccessFeed {
  access: AccessRead | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

// The allowlist / permissions / ban view is a plain fetch, kept live off the
// existing status stream: whenever the access block in status changes (an
// enforcement transition, a ban count change) it refetches, so the section
// reflects out-of-band changes without a reload (tasks 9.5, 9.7).
export function useAccess(): AccessFeed {
  const { status } = useStatus();
  const [access, setAccess] = useState<AccessRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .accessRead()
      .then((a) => {
        if (!cancelled) {
          // Defensive: only accept a well-formed payload so a partial response
          // never crashes the section.
          setAccess(a && a.enforcement && a.allowlist ? a : null);
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

  const accessKey = JSON.stringify(status?.access ?? null);
  const prevKey = useRef<string | null>(null);
  useEffect(() => {
    if (prevKey.current !== null && prevKey.current !== accessKey) reload();
    prevKey.current = accessKey;
  }, [accessKey, reload]);

  return { access, loading, error, reload };
}
