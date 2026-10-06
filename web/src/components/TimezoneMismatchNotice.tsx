import { useState } from "react";
import { ApiCallError } from "../api/client";
import {
  browserTimeZone,
  dismissMismatch,
  isMismatchDismissed,
  zonesMatch,
} from "../api/timezone";
import { useCobbleSettings } from "../api/useCobbleSettings";

/** Says so when this browser's zone and the zone cobble's schedules run in would
 *  put a clock time at different instants at some point in the coming year, and
 *  offers to switch cobble to the browser's zone (web-ui-shell: a timezone
 *  mismatch is surfaced). Dismissal is remembered per pair of zones. */
export function TimezoneMismatchNotice() {
  const { settings, save } = useCobbleSettings();
  const [dismissedKey, setDismissedKey] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!settings) return null;
  const browser = browserTimeZone();
  const cobble = settings.effective_timezone;
  const key = `${browser}|${cobble}`;
  if (zonesMatch(browser, cobble)) return null;
  if (dismissedKey === key || isMismatchDismissed(browser, cobble)) return null;

  const switchToBrowser = async () => {
    setSaving(true);
    setErr(null);
    try {
      await save(browser);
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="panel is-warn tz-mismatch" role="status">
      <strong>Schedules run in {cobble} time.</strong> This browser is in {browser}, so a
      time you set here is not that time on your clock.
      <div className="controls-row">
        <button className="btn" disabled={saving} onClick={() => void switchToBrowser()}>
          {saving ? "Switching…" : `Switch cobble to ${browser}`}
        </button>
        <button
          className="link"
          disabled={saving}
          onClick={() => {
            dismissMismatch(browser, cobble);
            setDismissedKey(key);
          }}
        >
          dismiss
        </button>
      </div>
      {err && <div className="controls-error">{err}</div>}
    </div>
  );
}
