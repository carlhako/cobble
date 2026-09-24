import { useState } from "react";
import Markdown, { type Components } from "react-markdown";
import { useStatus } from "../api/StatusContext";
import { useCobbleVersion } from "../api/useCobbleVersion";
import { ApiCallError, api, type CobbleVersion } from "../api/client";

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function fmtDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

// Release notes come from GitHub: raw HTML in them is never rendered (no
// rehype-raw), unsafe URLs are dropped by react-markdown's default
// urlTransform, and links leave the interface.
const NOTES_COMPONENTS: Components = {
  a: ({ node: _node, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
};

/** The latest release's notes, whether or not it is newer than this install
 *  (web-ui-shell: "The cobble page shows the latest release's notes"). */
function ReleaseNotes({ info }: { info: CobbleVersion }) {
  if (!info.latest) return null;
  const date = fmtDate(info.published_at);
  // GitHub titles a release with its tag unless someone names it; only show a
  // title that says more than the version already in the heading.
  const title =
    info.release_name?.replace(/^v/, "") === info.latest ? null : info.release_name;
  return (
    <div className="panel release-notes">
      <h2>What's new in {info.latest}</h2>
      <div className="muted">
        {title && <>{title} · </>}
        {date ? `Published ${date}` : "Publish date unknown"}
      </div>
      {info.notes ? (
        <div className="release-notes-body" aria-label="release notes">
          <Markdown components={NOTES_COMPONENTS}>{info.notes}</Markdown>
        </div>
      ) : (
        <p className="muted">No release notes were published for this release.</p>
      )}
    </div>
  );
}

/** cobble's own version and one-click upgrade (cobble-self-update; web-ui-shell:
 *  "Cobble upgrades are available from the cobble page"). Distinct from the
 *  Bedrock server's version on Updates & Backups. */
function CobbleCard({ info }: { info: CobbleVersion }) {
  const { status, stale } = useStatus();
  const { set } = useCobbleVersion();
  const [working, setWorking] = useState<null | "check" | "upgrade">(null);
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const u = info.upgrade;
  const inFlight = u?.state === "pending" || u?.state === "running";
  const busy = stale || !!status?.maintenance || inFlight;

  const call = async (kind: "check" | "upgrade", fn: () => Promise<CobbleVersion>) => {
    setWorking(kind);
    setErr(null);
    try {
      set(await fn());
      setConfirm(false);
    } catch (e) {
      setErr(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setWorking(null);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(info.manual_command ?? "");
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="panel cobble-card">
      <div className="cards">
        <div className="card">
          <div className="card-label">Installed</div>
          <div className="card-value">{info.current}</div>
        </div>
        <div className="card">
          <div className="card-label">Latest release</div>
          <div className="card-value">{info.latest ?? "unknown"}</div>
        </div>
        <div className="card">
          <div className="card-label">Status</div>
          <div className="card-value">
            {inFlight
              ? "Upgrading"
              : info.update_available
                ? "Update available"
                : info.latest
                  ? "Up to date"
                  : "Not checked"}
          </div>
        </div>
      </div>
      <div className="muted">
        Last checked {fmtTime(info.checked_at)}
        {info.release_url && (
          <>
            {" · "}
            <a href={info.release_url} target="_blank" rel="noopener noreferrer">
              View on GitHub
            </a>
          </>
        )}
      </div>
      {info.check_error && (
        <div className="muted">
          The last check could not reach GitHub: {info.check_error}
        </div>
      )}

      <div className="controls-row">
        <button
          className="btn"
          disabled={working !== null}
          onClick={() => void call("check", api.cobbleCheck)}
        >
          {working === "check" ? "Checking…" : "Check now"}
        </button>
        {info.update_available && info.one_click_available && info.latest && (
          <button
            className="btn"
            disabled={busy || working !== null}
            onClick={() => setConfirm(true)}
          >
            Upgrade to {info.latest}
          </button>
        )}
      </div>

      {info.update_available && !info.one_click_available && info.manual_command && (
        <div className="manual-upgrade">
          <p>
            This install predates one-click upgrades. To upgrade, run this as root on the
            container. Later upgrades can then be done from here.
          </p>
          <div className="controls-row">
            <code aria-label="manual upgrade command">{info.manual_command}</code>
            <button className="btn" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}

      {confirm && info.latest && (
        <div
          className="panel is-warn"
          role="alertdialog"
          aria-label="confirm cobble upgrade"
        >
          <strong>Upgrade cobble to {info.latest}?</strong>
          <p className="warn">
            The Bedrock server will be stopped and players disconnected. cobble takes a
            verified backup, installs {info.latest}, and restarts. The server comes back
            once the new cobble has started, and this page reloads by itself.
          </p>
          <div className="controls-row">
            <button
              className="btn btn-stop"
              disabled={busy || working !== null}
              onClick={() =>
                void call("upgrade", () => api.cobbleUpgrade(info.latest ?? ""))
              }
            >
              {working === "upgrade" ? "Backing up…" : "Back up and upgrade"}
            </button>
            <button
              className="btn"
              disabled={working !== null}
              onClick={() => setConfirm(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {err && <div className="controls-error">{err}</div>}

      {inFlight && u && (
        <div className="muted" role="status">
          Upgrade to {u.to}{" "}
          {u.state === "running" ? "is installing" : "is waiting for the helper"}…
        </div>
      )}
      {u && !inFlight && (
        <div className={u.state === "succeeded" ? "ok" : "warn"} role="status">
          Last upgrade: {u.from ?? "?"} → {u.to ?? "?"},{" "}
          {u.state === "succeeded" ? "succeeded" : u.state} {fmtTime(u.finished_at)}
          {u.error && <div>{u.error}</div>}
        </div>
      )}
      {u && !inFlight && u.state !== "succeeded" && u.log_tail && (
        <pre className="diag-output" aria-label="upgrade output">
          {u.log_tail}
        </pre>
      )}
    </div>
  );
}

/** The cobble page, opened from the header version badge; not in the nav bar. */
export function Cobble() {
  const { stale } = useStatus();
  const { info } = useCobbleVersion();
  return (
    <section className={`section cobble${stale ? " is-stale" : ""}`}>
      <h1>cobble (control panel)</h1>
      <p className="muted">
        The control panel itself, separate from the Bedrock server's version and updates
        on Updates &amp; Backups.
      </p>
      {info ? (
        <>
          <CobbleCard info={info} />
          <ReleaseNotes info={info} />
        </>
      ) : (
        <p className="muted">Loading…</p>
      )}
    </section>
  );
}
