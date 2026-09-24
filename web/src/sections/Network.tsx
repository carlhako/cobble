import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useStatus } from "../api/StatusContext";
import {
  ApiCallError,
  api,
  type NetworkLayout,
  type NetworkTransport,
  type NetworkView,
  type PendingChange,
  type ValidationIssue,
} from "../api/client";
import { ConflictBanner } from "../components/ConflictBanner";
import { PendingPanel } from "../components/PendingPanel";

const UDP_KEY = "server-udp-ports";

const TRANSPORTS: { value: NetworkTransport; label: string }[] = [
  { value: "nethernet", label: "NetherNet" },
  { value: "raknet", label: "RakNet (legacy)" },
];

type IssueMap = Record<string, string>;

function toIssueMap(issues: ValidationIssue[]): IssueMap {
  const out: IssueMap = {};
  for (const i of issues) out[i.key] = i.message;
  return out;
}

/** The section's editing state (design.md D6). `values` holds every port and
 *  address setting across both layouts; only the ones the chosen transport
 *  shows are ever submitted. */
interface Draft {
  transport: NetworkTransport;
  values: Record<string, string>;
  udpMode: "os" | "range";
  from: string;
  to: string;
}

/** The saved `server-udp-ports` as the range form would write it, or `null`
 *  for a custom value the form never touches. */
function savedUdp(view: NetworkView): string | null {
  const r = view.layouts.nethernet.udp_range;
  if (!r || r.form === "os") return "";
  if (r.form === "range") return r.start === r.end ? `${r.start}` : `${r.start}-${r.end}`;
  return null;
}

function draftFrom(view: NetworkView): Draft {
  const values: Record<string, string> = {};
  for (const layout of Object.values(view.layouts))
    for (const s of layout.settings) values[s.key] = s.value;
  const r = view.layouts.nethernet.udp_range;
  const range = r?.form === "range" ? r : null;
  return {
    transport: view.layout,
    values,
    udpMode: range ? "range" : "os",
    from: range ? String(range.start) : "",
    to: range ? String(range.end) : "",
  };
}

function composeUdp(d: Draft): string {
  if (d.udpMode === "os") return "";
  return d.from === d.to || d.to === "" ? d.from : `${d.from}-${d.to}`;
}

/** The changes a save sends: the transport and the settings its layout shows,
 *  each only when it differs from what is saved. A custom UDP value is never
 *  part of it. */
function changesFrom(view: NetworkView, d: Draft): Record<string, string> {
  const out: Record<string, string> = {};
  if (d.transport !== view.layout) out.transport = d.transport;
  for (const s of view.layouts[d.transport].settings) {
    if (s.key === UDP_KEY) {
      const saved = savedUdp(view);
      const next = composeUdp(d);
      if (saved !== null && next !== saved) out[UDP_KEY] = next;
    } else if (d.values[s.key] !== s.value) {
      out[s.key] = d.values[s.key];
    }
  }
  return out;
}

function UdpRangeField({
  layout,
  draft,
  onChange,
  disabled,
  error,
  warning,
}: {
  layout: NetworkLayout;
  draft: Draft;
  onChange: (patch: Partial<Draft>) => void;
  disabled: boolean;
  error?: string;
  warning?: string;
}) {
  const saved = layout.udp_range;
  if (saved?.form === "custom") {
    return (
      <div className="cfg-row">
        <span className="cfg-label">
          Player UDP ports <span className="badge">UDP</span>
        </span>
        <div className="cfg-control">
          <code aria-label="player UDP ports value">{saved.value}</code>
        </div>
        <div className="cfg-meta">
          <span className="muted">
            This value uses a form the range editor can't show (a NAT mapping, an address,
            or several entries). It confines the server to {saved.size} local port
            {saved.size === 1 ? "" : "s"}. Saving here leaves it unchanged; edit it in{" "}
            <Link to="/configuration">Configuration</Link>.
          </span>
          {warning && <span className="cfg-warn">{warning}</span>}
        </div>
      </div>
    );
  }

  const from = Number(draft.from);
  const to = Number(draft.to || draft.from);
  const size =
    draft.udpMode === "range" && draft.from !== "" && to >= from ? to - from + 1 : null;
  return (
    <div
      className={`cfg-row${error ? " has-error" : ""}`}
      role="group"
      aria-labelledby="net-udp-label"
    >
      <span id="net-udp-label" className="cfg-label">
        Player UDP ports <span className="badge">UDP</span>
      </span>
      <div className="cfg-control net-udp-choice">
        <label>
          <input
            type="radio"
            name="net-udp-mode"
            checked={draft.udpMode === "os"}
            disabled={disabled}
            onChange={() => onChange({ udpMode: "os" })}
          />{" "}
          Let the OS pick
        </label>
        <label>
          <input
            type="radio"
            name="net-udp-mode"
            checked={draft.udpMode === "range"}
            disabled={disabled}
            onChange={() => onChange({ udpMode: "range" })}
          />{" "}
          Pin a range
        </label>
        {draft.udpMode === "range" && (
          <span className="net-udp-range">
            <input
              type="number"
              aria-label="From port"
              min={1}
              max={65535}
              value={draft.from}
              disabled={disabled}
              onChange={(e) => onChange({ from: e.target.value })}
            />
            {" – "}
            <input
              type="number"
              aria-label="To port"
              min={1}
              max={65535}
              value={draft.to}
              disabled={disabled}
              onChange={(e) => onChange({ to: e.target.value })}
            />
            {size !== null && (
              <span className="muted">
                {" "}
                {size} port{size === 1 ? "" : "s"}
              </span>
            )}
          </span>
        )}
      </div>
      <div className="cfg-meta">
        <span className="muted">
          Each player connects on its own UDP port. Pin a range with at least as many
          ports as <code>max-players</code> to forward it for players outside your
          network. <code>{UDP_KEY}</code>
        </span>
        {error && <span className="cfg-error">{error}</span>}
        {warning && !error && <span className="cfg-warn">{warning}</span>}
      </div>
    </div>
  );
}

function ForwardPanel({ layout, stale }: { layout: NetworkLayout; stale: boolean }) {
  return (
    <div className="panel" role="region" aria-label="ports to forward">
      <h2>Forward on your router to this server's LAN address</h2>
      <p className="muted">For players outside your local network.</p>
      <ul className="net-forward">
        {layout.forward.map((f) => (
          <li key={`${f.protocol} ${f.ports}`}>
            <code>
              {f.protocol.toUpperCase()} {f.ports}
            </code>
            {f.note && <span className="muted"> · {f.note}</span>}
          </li>
        ))}
      </ul>
      {layout.pin_required && (
        <p className="cfg-warn">
          Players outside your network can't connect yet. The OS picks the player UDP
          ports, so there's no range to forward: pin one above and save.
        </p>
      )}
      {stale && (
        <p className="muted">This list reflects the saved settings. Save to update it.</p>
      )}
    </div>
  );
}

export function Network() {
  const { status, stale } = useStatus();
  const maintenance = status?.maintenance ?? null;
  const running = status?.run_state === "running";
  const pendingSig = status?.config?.pending_count ?? 0;

  const [view, setView] = useState<NetworkView | null>(null);
  const [pending, setPending] = useState<PendingChange[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<IssueMap>({});
  const [warnings, setWarnings] = useState<IssueMap>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedOnce, setSavedOnce] = useState(false);

  const load = useCallback(async (): Promise<NetworkView | null> => {
    try {
      const [v, r] = await Promise.all([api.getNetwork(), api.configRead()]);
      setView(v);
      setPending(r.pending);
      setLoadError(null);
      return v;
    } catch (e) {
      setLoadError(e instanceof ApiCallError ? e.message : String(e));
      return null;
    }
  }, []);

  // Re-read when a save or a start/restart changes what is pending, as the
  // Configuration section does; the draft is kept.
  useEffect(() => {
    void load();
  }, [load, pendingSig, running]);

  useEffect(() => {
    if (view && !draft) setDraft(draftFrom(view));
  }, [view, draft]);

  const changes = useMemo(
    () => (view && draft ? changesFrom(view, draft) : {}),
    [view, draft],
  );
  const dirty = Object.keys(changes).length > 0;

  const patch = (p: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...p } : d));
  const setValue = (key: string, v: string) =>
    setDraft((d) => (d ? { ...d, values: { ...d.values, [key]: v } } : d));

  const save = async () => {
    setSaving(true);
    try {
      const result = await api.configWrite(changes);
      if (result.ok) {
        setErrors({});
        setWarnings(toIssueMap(result.warnings));
        setSavedOnce(true);
        const v = await load();
        if (v) setDraft(draftFrom(v));
      } else {
        // Keep the draft; show the reason beside each rejected setting.
        setErrors(toIssueMap(result.errors));
        setWarnings(toIssueMap(result.warnings));
      }
    } catch (e) {
      setErrors({ _: e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e) });
    } finally {
      setSaving(false);
    }
  };

  if (loadError && !view) {
    return (
      <section className="section network">
        <h1>Network</h1>
        <div className="panel is-error" role="alert">
          Could not load the network settings: {loadError}
        </div>
      </section>
    );
  }

  const readOnly = maintenance !== null || stale;
  const layout = view && draft ? view.layouts[draft.transport] : null;

  return (
    <section className={`section network${stale ? " is-stale" : ""}`}>
      <h1>Network</h1>

      <ConflictBanner conflicts={view?.conflicts ?? []} />

      {maintenance && (
        <div className="panel is-busy" role="status">
          <strong>
            Saving is unavailable —{" "}
            {maintenance.operation === "updating"
              ? "an update"
              : maintenance.operation === "restoring"
                ? "a restore"
                : "a backup"}{" "}
            is in progress.
          </strong>
          {maintenance.step && <span className="muted"> · {maintenance.step}</span>}
        </div>
      )}

      <PendingPanel pending={pending} running={running} onRestarted={load} />

      {savedOnce && Object.keys(errors).length === 0 && !dirty && (
        <div className="ok" role="status">
          Saved.
        </div>
      )}
      {errors._ && <div className="controls-error">{errors._}</div>}

      {!view || !draft || !layout ? (
        <div className="panel">
          <p className="muted">Loading…</p>
        </div>
      ) : (
        <>
          <div className="panel">
            <h2>How players connect</h2>
            <div className="cfg-list">
              <div className={`cfg-row${errors.transport ? " has-error" : ""}`}>
                <label htmlFor="net-transport" className="cfg-label">
                  Transport
                </label>
                <div className="cfg-control">
                  <select
                    id="net-transport"
                    value={draft.transport}
                    disabled={readOnly}
                    onChange={(e) =>
                      patch({ transport: e.target.value as NetworkTransport })
                    }
                  >
                    {TRANSPORTS.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="cfg-meta">
                  <span className="muted">
                    The settings below are for the transport the next start will use.
                  </span>
                  {view.transport.pending_restart && (
                    <span className="cfg-warn">
                      The server is still running {view.transport.value} until it
                      restarts.
                    </span>
                  )}
                  {errors.transport && (
                    <span className="cfg-error">{errors.transport}</span>
                  )}
                </div>
              </div>

              {layout.settings.map((s) =>
                s.key === UDP_KEY ? (
                  <UdpRangeField
                    key={s.key}
                    layout={layout}
                    draft={draft}
                    onChange={patch}
                    disabled={readOnly}
                    error={errors[s.key]}
                    warning={warnings[s.key]}
                  />
                ) : (
                  <div
                    key={s.key}
                    className={`cfg-row${errors[s.key] ? " has-error" : ""}`}
                  >
                    <label htmlFor={`net-${s.key}`} className="cfg-label">
                      {s.label}
                      {s.protocol && (
                        <span className="badge">{s.protocol.toUpperCase()}</span>
                      )}
                    </label>
                    <div className="cfg-control">
                      <input
                        id={`net-${s.key}`}
                        type={s.protocol ? "number" : "text"}
                        placeholder={s.protocol ? undefined : "all interfaces"}
                        value={draft.values[s.key] ?? ""}
                        disabled={readOnly}
                        onChange={(e) => setValue(s.key, e.target.value)}
                      />
                    </div>
                    <div className="cfg-meta">
                      <span className="muted">
                        <code>{s.key}</code>
                        {!s.present && " · not set, the default applies"}
                      </span>
                      {errors[s.key] && (
                        <span className="cfg-error">{errors[s.key]}</span>
                      )}
                      {warnings[s.key] && !errors[s.key] && (
                        <span className="cfg-warn">{warnings[s.key]}</span>
                      )}
                    </div>
                  </div>
                ),
              )}

              {layout.lan_discovery && (
                <div className="cfg-row">
                  <span className="cfg-label">LAN discovery</span>
                  <div className="cfg-control">
                    <code>
                      {layout.lan_discovery.protocol.toUpperCase()}{" "}
                      {layout.lan_discovery.port}
                    </code>
                  </div>
                  <div className="cfg-meta">
                    <span className="muted">
                      For information: how players on your local network find the server.
                      It is fixed and doesn't need forwarding.
                    </span>
                  </div>
                </div>
              )}
            </div>

            {!readOnly && (
              <div className="controls-row">
                <button
                  className="btn btn-start"
                  disabled={saving || !dirty}
                  onClick={() => void save()}
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                {dirty && (
                  <button
                    className="link"
                    disabled={saving}
                    onClick={() => {
                      setDraft(draftFrom(view));
                      setErrors({});
                    }}
                  >
                    discard
                  </button>
                )}
              </div>
            )}
            {maintenance && (
              <div className="controls-row">
                <span className="controls-status">
                  Network settings are read-only during maintenance.
                </span>
              </div>
            )}
          </div>

          <ForwardPanel layout={layout} stale={dirty} />
        </>
      )}
    </section>
  );
}
