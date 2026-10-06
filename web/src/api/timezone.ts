// Time-zone helpers shared by the schedule screens and the cobble settings
// (web-ui-shell: schedule times are presented in the cobble timezone).

/** The browser's IANA zone, e.g. "Australia/Brisbane". */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** A host zone that cobble could only name by its offset ("+00:00"). */
const FIXED_OFFSET = /^([+-])(\d{2}):(\d{2})$/;

/** An instant as a clock time in `zone`, with the zone named, e.g.
 *  "Oct 7, 2026, 4:00 AM Australia/Brisbane". Without a zone the browser's own
 *  is used and nothing is named. */
export function formatInZone(iso: string | null, zone?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (!zone) return d.toLocaleString();
  const fixed = FIXED_OFFSET.exec(zone);
  try {
    const text = new Intl.DateTimeFormat(undefined, {
      // A fixed-offset host zone is not an IANA name; render it in UTC shifted.
      timeZone: fixed ? "UTC" : zone,
      dateStyle: "medium",
      timeStyle: "short",
    }).format(fixed ? new Date(d.getTime() + fixedOffsetMinutes(fixed) * 60_000) : d);
    return `${text} ${zone}`;
  } catch {
    return d.toLocaleString();
  }
}

function fixedOffsetMinutes(m: RegExpExecArray): number {
  const minutes = Number(m[2]) * 60 + Number(m[3]);
  return m[1] === "-" ? -minutes : minutes;
}

/** The UTC offset of `zone` at `at`, in minutes. */
function offsetMinutes(zone: string, at: Date): number {
  const fixed = FIXED_OFFSET.exec(zone);
  if (fixed) return fixedOffsetMinutes(fixed);
  const part = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    timeZoneName: "longOffset",
  })
    .formatToParts(at)
    .find((p) => p.type === "timeZoneName")?.value;
  // "GMT" for UTC, otherwise "GMT+10:00" / "GMT-03:30".
  const m = /^GMT(?:([+-])(\d{1,2})(?::(\d{2}))?)?$/.exec(part ?? "");
  if (!m) throw new RangeError(`unreadable offset for ${zone}: ${part}`);
  if (!m[1]) return 0;
  const minutes = Number(m[2]) * 60 + Number(m[3] ?? 0);
  return m[1] === "-" ? -minutes : minutes;
}

/** Sample dates over the coming year: the 1st and 15th of each month, plus now.
 *  Twice-monthly sampling can miss a DST period shorter than about two weeks,
 *  which no current zone has. */
function sampleDates(from: Date): Date[] {
  const out = [from];
  for (let i = 0; i < 12; i++) {
    out.push(new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth() + i, 1, 12)));
    out.push(new Date(Date.UTC(from.getUTCFullYear(), from.getUTCMonth() + i, 15, 12)));
  }
  return out;
}

/** Two zones match when they have the same UTC offset at every sample point in
 *  the coming 12 months, so aliases and same-rule cities count as the same while
 *  zones that differ only during daylight saving do not. A zone the browser
 *  cannot resolve is treated as not matching. */
export function zonesMatch(a: string, b: string, from: Date = new Date()): boolean {
  if (a === b) return true;
  try {
    return sampleDates(from).every((d) => offsetMinutes(a, d) === offsetMinutes(b, d));
  } catch {
    return false;
  }
}

// -- dismissing the mismatch notice, per pair of zones ----------------------
const DISMISS_PREFIX = "cobble.tzMismatchDismissed:";

function dismissKey(browser: string, cobble: string): string {
  return `${DISMISS_PREFIX}${browser}|${cobble}`;
}

/** Storage can be absent or throw (private windows, blocked site data); the
 *  notice then simply shows. */
export function isMismatchDismissed(browser: string, cobble: string): boolean {
  try {
    return window.localStorage.getItem(dismissKey(browser, cobble)) === "1";
  } catch {
    return false;
  }
}

export function dismissMismatch(browser: string, cobble: string): void {
  try {
    window.localStorage.setItem(dismissKey(browser, cobble), "1");
  } catch {
    // Not persisted; the dismissal lasts for this view only.
  }
}
