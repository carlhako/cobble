import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, type CobbleVersion } from "./client";

// cobble's own version and release state (cobble-self-update). The backend
// caches one GitHub check for everyone, so polling it is cheap: every few
// minutes normally, every few seconds while an upgrade is in flight.
export const VERSION_POLL_MS = 5 * 60 * 1000;
export const UPGRADE_POLL_MS = 3000;

export interface CobbleVersionState {
  info: CobbleVersion | null;
  refresh: () => Promise<void>;
  set: (info: CobbleVersion) => void;
}

function upgradeInFlight(info: CobbleVersion | null): boolean {
  const s = info?.upgrade?.state;
  return s === "pending" || s === "running";
}

/** Fetches the version on mount and on an interval. While an upgrade is in
 *  flight it also watches `/health`: cobble goes away while the helper
 *  installs, and comes back as a different version. When it does, the page
 *  reloads onto the new interface. Connection errors are expected here and
 *  ignored. */
function useCobbleVersionState(enabled: boolean): CobbleVersionState {
  const [info, setInfo] = useState<CobbleVersion | null>(null);
  const loadedVersion = useRef<string | null>(null);

  const set = useCallback((next: CobbleVersion) => {
    loadedVersion.current ??= next.current;
    setInfo(next);
  }, []);

  const refresh = useCallback(async () => {
    try {
      set(await api.cobbleVersion());
    } catch {
      // Unknown until the next poll; the header simply shows nothing new.
    }
  }, [set]);

  useEffect(() => {
    if (!enabled) return;
    void refresh();
    const id = window.setInterval(() => void refresh(), VERSION_POLL_MS);
    return () => window.clearInterval(id);
  }, [enabled, refresh]);

  const following = enabled && upgradeInFlight(info);
  useEffect(() => {
    if (!following) return;
    const id = window.setInterval(() => {
      void (async () => {
        try {
          const resp = await fetch("/health", { cache: "no-store" });
          const body = (await resp.json()) as { version?: string };
          if (
            body.version &&
            loadedVersion.current &&
            body.version !== loadedVersion.current
          ) {
            window.location.reload();
            return;
          }
        } catch {
          return; // cobble is restarting
        }
        await refresh(); // still the old cobble: pick up a failed outcome
      })();
    }, UPGRADE_POLL_MS);
    return () => window.clearInterval(id);
  }, [following, refresh]);

  return { info, refresh, set };
}

const CobbleVersionContext = createContext<CobbleVersionState | null>(null);

export function CobbleVersionProvider({ children }: { children: ReactNode }) {
  const value = useCobbleVersionState(true);
  return (
    <CobbleVersionContext.Provider value={value}>
      {children}
    </CobbleVersionContext.Provider>
  );
}

/** The shared version state inside the shell; a self-contained instance when
 *  rendered outside it (e.g. a section rendered on its own). */
// eslint-disable-next-line react-refresh/only-export-components
export function useCobbleVersion(): CobbleVersionState {
  const ctx = useContext(CobbleVersionContext);
  const local = useCobbleVersionState(ctx === null);
  return ctx ?? local;
}
