import { useCallback, useEffect, useMemo, useState } from "react";
import { useStatus } from "../api/StatusContext";
import {
  ApiCallError,
  api,
  type GameruleCatalogueEntry,
  type GameruleDefaults,
  type GameruleReport,
  type GameruleRow,
  type GameruleValue,
  type GameruleView,
} from "../api/client";

function formatWhen(iso: string | null): string {
  if (!iso) return "unknown";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function displayValue(v: GameruleValue): string {
  return typeof v === "boolean" ? (v ? "true" : "false") : String(v);
}

/** A single rule, rendered with a control matching its type (6.1). Fully
 *  controlled by the server-reported value: a change is applied immediately and
 *  the value shown afterwards is whatever the server reports back (6.2 / 6.3). */
function RuleControl({
  row,
  disabled,
  busy,
  error,
  nonce,
  onApply,
}: {
  row: GameruleRow;
  disabled: boolean;
  busy: boolean;
  error?: string;
  nonce: number;
  onApply: (next: GameruleValue) => void;
}) {
  const id = `gr-${row.name}`;
  let control: React.ReactNode;

  if (row.type === "bool") {
    control = (
      <input
        id={id}
        type="checkbox"
        checked={row.value === true}
        disabled={disabled || busy}
        onChange={(e) => onApply(e.target.checked)}
      />
    );
  } else if (row.type === "int") {
    control = (
      <input
        id={id}
        type="number"
        step={1}
        min={row.minimum ?? undefined}
        max={row.maximum ?? undefined}
        defaultValue={String(row.value)}
        key={`${row.name}:${String(row.value)}:${nonce}`}
        disabled={disabled || busy}
        onBlur={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n) && n !== Number(row.value)) onApply(n);
        }}
      />
    );
  } else if (row.type === "enum" && row.members && row.members.length > 0) {
    control = (
      <select
        id={id}
        value={String(row.value)}
        disabled={disabled || busy}
        onChange={(e) => onApply(e.target.value)}
      >
        {!row.members.includes(String(row.value)) && (
          <option value={String(row.value)}>{String(row.value)}</option>
        )}
        {row.members.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    );
  } else {
    // unrecognised, or a recognised rule with no usable type info: editable text
    control = (
      <input
        id={id}
        type="text"
        defaultValue={displayValue(row.value)}
        key={`${row.name}:${displayValue(row.value)}:${nonce}`}
        disabled={disabled || busy}
        onBlur={(e) => {
          if (e.target.value !== displayValue(row.value)) onApply(e.target.value);
        }}
      />
    );
  }

  return (
    <div className={`cfg-row${error ? " has-error" : ""}`}>
      <label htmlFor={id} className="cfg-label">
        {row.name}
        {!row.recognised && (
          <span className="badge" title="cobble has no type information for this rule">
            unrecognised
          </span>
        )}
      </label>
      <div className="cfg-control">{control}</div>
      <div className="cfg-meta">
        {row.description && <span className="muted">{row.description}</span>}
        {row.type === "int" && (row.minimum != null || row.maximum != null) && (
          <span className="muted">
            {" "}
            · range {row.minimum ?? "?"}–{row.maximum ?? "?"}
          </span>
        )}
        {error && <span className="cfg-error">{error}</span>}
      </div>
    </div>
  );
}

/** 6.6 — an adoption / repair / defaults report cobble performed, with the rules
 *  and values it set, and a control to dismiss it. */
function ReportPanel({
  report,
  onAcknowledge,
  working,
}: {
  report: GameruleReport;
  onAcknowledge: () => void;
  working: boolean;
}) {
  const heading =
    report.kind === "adoption"
      ? "A gamerule was changed outside cobble"
      : report.kind === "repair"
        ? "Gamerules were re-applied after a restore"
        : "Preferred defaults were applied to this world";
  const explain =
    report.kind === "adoption"
      ? "cobble saved the new value as this world's record. It did not change anything on the server."
      : report.kind === "repair"
        ? "A restore reverted this world's gamerules, so cobble put the recorded values back."
        : "cobble had not seen this world before and applied your preferred defaults.";
  const entries = Object.entries(report.rules);

  return (
    <div className="panel is-warn" role="status" aria-label="gamerule report">
      <strong>{heading}</strong>
      <p className="muted">{explain}</p>
      <table className="cfg-pending">
        <thead>
          <tr>
            <th>Rule</th>
            <th>Value</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([name, value]) => (
            <tr key={name}>
              <td>{name}</td>
              <td>{displayValue(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="controls-row">
        <button className="btn" disabled={working} onClick={onAcknowledge}>
          {working ? "Dismissing…" : "Acknowledge"}
        </button>
      </div>
    </div>
  );
}

/** 6.7 — the preferred-defaults editor. Presented separately from the active
 *  world's values, and it applies only to worlds cobble has not seen before. */
function DefaultsEditor({ disabled }: { disabled: boolean }) {
  const [data, setData] = useState<GameruleDefaults | null>(null);
  const [addName, setAddName] = useState("");
  const [addValue, setAddValue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.gamerulesDefaults());
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const byName = useMemo(() => {
    const m = new Map<string, GameruleCatalogueEntry>();
    for (const c of data?.catalogue ?? []) m.set(c.name, c);
    return m;
  }, [data]);

  const set = async (name: string, value: GameruleValue) => {
    setWorking(true);
    setErr(null);
    try {
      setData(await api.gamerulesSetDefault(name, value));
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  };
  const clear = async (name: string) => {
    setWorking(true);
    setErr(null);
    try {
      setData(await api.gamerulesClearDefault(name));
    } catch (e) {
      setErr(e instanceof ApiCallError ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  };

  if (!data) return null;
  const defaults = data.defaults ?? {};
  const catalogue = data.catalogue ?? [];
  const current = Object.entries(defaults);
  const unset = catalogue.filter((c) => !(c.name in defaults));

  const coerce = (name: string, raw: string): GameruleValue => {
    const c = byName.get(name);
    if (c?.type === "bool") return raw === "true";
    if (c?.type === "int") return Number(raw);
    return raw;
  };

  return (
    <div className="panel" aria-label="preferred gamerule defaults">
      <h2>Preferred defaults for new worlds</h2>
      <p className="muted">
        These are applied once to a world cobble has not seen before. They do not affect
        worlds cobble already has a record of — including the world shown above.
      </p>
      {current.length === 0 ? (
        <p className="muted">No preferred defaults set.</p>
      ) : (
        <div className="cfg-list">
          {current.map(([name, value]) => {
            const c = byName.get(name);
            return (
              <div className="cfg-row" key={name}>
                <label className="cfg-label" htmlFor={`grd-${name}`}>
                  {name}
                </label>
                <div className="cfg-control">
                  {c?.type === "bool" ? (
                    <input
                      id={`grd-${name}`}
                      type="checkbox"
                      checked={value === true}
                      disabled={disabled || working}
                      onChange={(e) => set(name, e.target.checked)}
                    />
                  ) : c?.type === "enum" && c.members.length > 0 ? (
                    <select
                      id={`grd-${name}`}
                      value={String(value)}
                      disabled={disabled || working}
                      onChange={(e) => set(name, e.target.value)}
                    >
                      {c.members.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id={`grd-${name}`}
                      type={c?.type === "int" ? "number" : "text"}
                      defaultValue={String(value)}
                      key={`${name}:${String(value)}`}
                      disabled={disabled || working}
                      onBlur={(e) => set(name, coerce(name, e.target.value))}
                    />
                  )}
                </div>
                <div className="cfg-meta">
                  <button
                    type="button"
                    className="link"
                    disabled={disabled || working}
                    onClick={() => clear(name)}
                  >
                    remove
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="controls-row">
        <select
          aria-label="rule to add as a default"
          value={addName}
          disabled={disabled || working}
          onChange={(e) => {
            setAddName(e.target.value);
            const c = byName.get(e.target.value);
            setAddValue(c ? displayValue(c.default) : "");
          }}
        >
          <option value="">Add a default…</option>
          {unset.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
        {addName && (
          <>
            <input
              aria-label="default value"
              type="text"
              value={addValue}
              disabled={disabled || working}
              onChange={(e) => setAddValue(e.target.value)}
            />
            <button
              type="button"
              className="btn btn-start"
              disabled={disabled || working}
              onClick={async () => {
                await set(addName, coerce(addName, addValue));
                setAddName("");
                setAddValue("");
              }}
            >
              Add
            </button>
          </>
        )}
      </div>
      {err && <div className="controls-error">{err}</div>}
    </div>
  );
}

export function Gamerules() {
  const { status, stale } = useStatus();
  const maintenance = status?.maintenance ?? null;
  const running = status?.run_state === "running";

  const [view, setView] = useState<GameruleView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<Record<string, string>>({});
  const [busyRule, setBusyRule] = useState<string | null>(null);
  const [queuedNote, setQueuedNote] = useState<string | null>(null);
  const [ackWorking, setAckWorking] = useState(false);
  // Bumped on a refusal so an uncontrolled number/text input remounts and
  // reverts to the value in effect (6.3).
  const [nonce, setNonce] = useState(0);

  const readSig = status?.gamerules?.last_read_at ?? "";
  const reportSig = status?.gamerules?.report?.created_at ?? "";

  const load = useCallback(async () => {
    try {
      setView(await api.gamerulesRead());
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiCallError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, running, readSig, reportSig]);

  const editingDisabled = maintenance !== null || stale;

  const apply = async (row: GameruleRow, next: GameruleValue) => {
    setBusyRule(row.name);
    setQueuedNote(null);
    setRowError((prev) => {
      const rest = { ...prev };
      delete rest[row.name];
      return rest;
    });
    try {
      const res = await api.gamerulesWrite(row.name, next);
      if (res.queued) {
        // 6.5 — a change made while the server is stopped applies at next start.
        setQueuedNote(
          `${row.name} = ${displayValue(next)} will be applied when the server next starts.`,
        );
        await load();
      } else if (res.rules) {
        // 6.2 — show the value the server read back, no restart prompt.
        setView((v) => (v ? { ...v, rules: res.rules ?? v.rules } : v));
      }
    } catch (e) {
      // 6.3 — show the reason against the rule and revert to the value in effect.
      setRowError((prev) => ({
        ...prev,
        [row.name]: e instanceof ApiCallError ? e.message : String(e),
      }));
      setNonce((n) => n + 1);
      await load();
    } finally {
      setBusyRule(null);
    }
  };

  const acknowledge = async () => {
    setAckWorking(true);
    try {
      await api.gamerulesAcknowledge();
      await load();
    } catch {
      // leave the report visible; the next status push will retry the load
    } finally {
      setAckWorking(false);
    }
  };

  if (loadError && !view) {
    return (
      <section className="section gamerules">
        <h1>Gamerules</h1>
        <div className="panel is-error" role="alert">
          Could not load gamerules: {loadError}
        </div>
      </section>
    );
  }

  return (
    <section className={`section gamerules${stale ? " is-stale" : ""}`}>
      <h1>Gamerules</h1>

      {maintenance && (
        <div className="panel is-busy" role="status">
          <strong>
            Editing is unavailable —{" "}
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

      {view?.report && (
        <ReportPanel
          report={view.report}
          working={ackWorking}
          onAcknowledge={acknowledge}
        />
      )}

      {view && view.liveness === "recorded" && (
        <div className="panel is-warn" role="status">
          The server is not running. These are the values recorded for{" "}
          <strong>{view.level_name}</strong> on {formatWhen(view.sampled_at)}, not the
          live values.
        </div>
      )}

      {queuedNote && (
        <div className="panel is-warn" role="status">
          {queuedNote}
        </div>
      )}

      {view && view.liveness === "unread" ? (
        <div className="panel" role="status">
          <p className="muted">
            The gamerules for <strong>{view.level_name}</strong> have not been read. Start
            the server to read them.
          </p>
        </div>
      ) : (
        <div className="panel">
          <h2>
            {view?.level_name}
            {view && (
              <span className="muted">
                {" "}
                — {view.liveness === "live" ? "live" : "recorded"}
              </span>
            )}
          </h2>
          {!view ? (
            <p className="muted">Loading…</p>
          ) : (
            <div className="cfg-list">
              {view.rules.map((row) => (
                <RuleControl
                  key={row.name}
                  row={row}
                  disabled={editingDisabled}
                  busy={busyRule === row.name}
                  error={rowError[row.name]}
                  nonce={nonce}
                  onApply={(next) => void apply(row, next)}
                />
              ))}
            </div>
          )}
          {editingDisabled && maintenance && (
            <p className="controls-status">Rules are read-only during maintenance.</p>
          )}
        </div>
      )}

      <DefaultsEditor disabled={editingDisabled} />
    </section>
  );
}
