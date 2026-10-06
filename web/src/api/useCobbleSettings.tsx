import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, type CobbleSettings } from "./client";

export interface CobbleSettingsState {
  /** null until the first read succeeds (or when it cannot be read). */
  settings: CobbleSettings | null;
  /** Save a zone (`null` = the host default). Rejects with the server's
   *  reason when the name is not accepted. */
  save: (timezone: string | null) => Promise<void>;
}

function isSettings(v: unknown): v is CobbleSettings {
  return (
    typeof v === "object" &&
    v !== null &&
    typeof (v as CobbleSettings).effective_timezone === "string"
  );
}

function useCobbleSettingsState(enabled: boolean): CobbleSettingsState {
  const [settings, setSettings] = useState<CobbleSettings | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void (async () => {
      try {
        const next = await api.cobbleSettings();
        if (live && isSettings(next)) setSettings(next);
      } catch {
        // Unknown: schedule times fall back to the browser's own zone.
      }
    })();
    return () => {
      live = false;
    };
  }, [enabled]);

  const save = useCallback(async (timezone: string | null) => {
    const next = await api.cobbleSettingsWrite(timezone);
    if (isSettings(next)) setSettings(next);
  }, []);

  return { settings, save };
}

const CobbleSettingsContext = createContext<CobbleSettingsState | null>(null);

export function CobbleSettingsProvider({ children }: { children: ReactNode }) {
  const value = useCobbleSettingsState(true);
  return (
    <CobbleSettingsContext.Provider value={value}>
      {children}
    </CobbleSettingsContext.Provider>
  );
}

/** The shared cobble settings inside the shell; a self-contained instance when
 *  rendered outside it (e.g. a section rendered on its own). */
// eslint-disable-next-line react-refresh/only-export-components
export function useCobbleSettings(): CobbleSettingsState {
  const ctx = useContext(CobbleSettingsContext);
  const local = useCobbleSettingsState(ctx === null);
  return ctx ?? local;
}
