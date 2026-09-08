import { useCallback, useEffect, useMemo, useState } from "react";
import { useStatus } from "../api/StatusContext";
import {
  ApiCallError,
  api,
  type ConfigRead,
  type ConfigSetting,
  type ValidationIssue,
  type WorldsView,
} from "../api/client";

const LEVEL_KEY = "level-name";

type IssueMap = Record<string, string>;

function toIssueMap(issues: ValidationIssue[]): IssueMap {
  const out: IssueMap = {};
  for (const i of issues) out[i.key] = i.message;
  return out;
}

/** One recognised/unrecognised setting, rendered with an input matching its type. */
function SettingRow({
  setting,
  value,
  onChange,
  error,
  warning,
}: {
  setting: ConfigSetting;
  value: string;
  onChange: (v: string) => void;
  error?: string;
  warning?: string;
}) {
  const s = setting.schema;
  const id = `cfg-${setting.key}`;
  let control: React.ReactNode;
  if (s?.type === "bool") {
    control = (
      <input
        id={id}
        type="checkbox"
        checked={value === "true"}
        onChange={(e) => onChange(e.target.checked ? "true" : "false")}
      />
    );
  } else if (s?.type === "enum" && s.members) {
    control = (
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {!s.members.includes(value) && <option value={value}>{value}</option>}
        {s.members.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    );
  } else if (s?.type === "int" || s?.type === "float") {
    control = (
      <input
        id={id}
        type="number"
        step={s.type === "float" ? "any" : 1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  } else {
    control = (
      <input
        id={id}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <div className={`cfg-row${error ? " has-error" : ""}`}>
      <label htmlFor={id} className="cfg-label">
        {setting.key}
        {!setting.recognised && (
          <span className="badge" title="cobble does not recognise this setting">
            not recognised
          </span>
        )}
      </label>
      <div className="cfg-control">{control}</div>
      <div className="cfg-meta">
        {s && <span className="muted">{s.description}</span>}
        {s && (
          <span className="muted">
            {" "}
            Default: <code>{s.default === "" ? "(empty)" : s.default}</code>
            {(s.type === "int" || s.type === "float") &&
              (s.minimum != null || s.maximum != null) && (
                <>
                  {" "}
                  · range {s.minimum ?? "?"}–{s.maximum ?? "?"}
                </>
              )}
          </span>
        )}
        {error && <span className="cfg-error">{error}</span>}
        {warning && !error && <span className="cfg-warn">{warning}</span>}
      </div>
    </div>
  );
}

/** 7.4 — the level setting as a choice among existing worlds, with creating a new
 *  world an explicit, separately labelled and confirmed action. */
function LevelPicker({
  worlds,
  value,
  onChange,
  onCreateAndSave,
  disabled,
}: {
  worlds: WorldsView;
  value: string;
  onChange: (v: string) => void;
  onCreateAndSave: (name: string) => void;
  disabled: boolean;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const present = worlds.worlds.some((w) => w.name === value);

  return (
    <div className="cfg-row cfg-level">
      <label htmlFor="cfg-level" className="cfg-label">
        {LEVEL_KEY}
      </label>
      <div className="cfg-control">
        <select
          id="cfg-level"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {!present && <option value={value}>{value} (missing)</option>}
          {worlds.worlds.map((w) => (
            <option key={w.name} value={w.name}>
              {w.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="link"
          disabled={disabled}
          onClick={() => setCreating((c) => !c)}
        >
          Create a new world…
        </button>
      </div>
      <div className="cfg-meta">
        <span className="muted">
          Selects which world under <code>worlds/</code> the server loads.
        </span>
        {!present && (
          <span className="cfg-warn">
            No world named “{value}” exists. It will be created empty at the next start.
          </span>
        )}
        {creating && (
          <div
            className="panel is-warn cfg-new-world"
            role="alertdialog"
            aria-label="create a new world"
          >
            <strong>Create a new world</strong>
            <p className="muted">
              A new, empty world will be created when the server next starts. The existing
              worlds are kept on disk and in backups.
            </p>
            <div className="controls-row">
              <input
                type="text"
                aria-label="new world name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="World name"
              />
              <button
                type="button"
                className="btn btn-start"
                disabled={disabled || name.trim() === ""}
                onClick={() => {
                  onCreateAndSave(name.trim());
                  setCreating(false);
                  setName("");
                }}
              >
                Create and save
              </button>
              <button type="button" className="btn" onClick={() => setCreating(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** 7.5 / 7.6 — pending changes and the restart that applies them. */
function PendingPanel({
  read,
  running,
  onRestarted,
}: {
  read: ConfigRead;
  running: boolean;
  onRestarted: () => void;
}) {
  const [working, setWorking] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [deferred, setDeferred] = useState(false);

  if (read.pending.length === 0) return null;

  const restart = async () => {
    setWorking(true);
    setErr(null);
    try {
      await api.restart();
      onRestarted();
    } catch (e) {
      setErr(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setWorking(false);
    }
  };

  return (
    <div
      className="panel is-warn"
      role="status"
      aria-label="pending configuration changes"
    >
      <strong>
        {read.pending.length} saved setting{read.pending.length === 1 ? "" : "s"} not yet
        in effect
      </strong>
      <p className="muted">
        The server reads its configuration only when it starts. These changes take effect
        the next time the server starts for any reason — an operator restart, a crash
        recovery, or an update.
      </p>
      <table className="cfg-pending">
        <thead>
          <tr>
            <th>Setting</th>
            <th>Saved</th>
            <th>In effect</th>
          </tr>
        </thead>
        <tbody>
          {read.pending.map((c) => (
            <tr key={c.key}>
              <td>{c.key}</td>
              <td>{c.saved ?? "(unset)"}</td>
              <td>{c.in_effect ?? "(unset)"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {running && !deferred && (
        <div className="controls-row">
          <button className="btn btn-restart" disabled={working} onClick={restart}>
            {working ? "Restarting…" : "Restart now to apply"}
          </button>
          <button className="btn" disabled={working} onClick={() => setDeferred(true)}>
            Later
          </button>
        </div>
      )}
      {running && deferred && (
        <p className="muted">
          Deferred. The changes will take effect the next time the server starts for any
          reason.
        </p>
      )}
      {err && <div className="controls-error">{err}</div>}
    </div>
  );
}

export function Configuration() {
  const { status, stale } = useStatus();
  const maintenance = status?.maintenance ?? null;
  const running = status?.run_state === "running";

  const [read, setRead] = useState<ConfigRead | null>(null);
  const [worlds, setWorlds] = useState<WorldsView | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<IssueMap>({});
  const [warnings, setWarnings] = useState<IssueMap>({});
  const [notes, setNotes] = useState<string[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedOnce, setSavedOnce] = useState(false);
  const pendingSig = status?.config?.pending_count ?? 0;

  const load = useCallback(async () => {
    try {
      const [r, w] = await Promise.all([api.configRead(), api.configWorlds()]);
      setRead(r);
      setWorlds(w);
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiCallError ? e.message : String(e));
    }
  }, []);

  // Load on mount and whenever the pushed pending count changes (a save here, or
  // a start/restart) so the pending panel reflects server-side fact — 7.6.
  useEffect(() => {
    void load();
  }, [load, pendingSig, running]);

  const valueFor = useCallback(
    (key: string, stored: string) => (key in edits ? edits[key] : stored),
    [edits],
  );

  const setEdit = (key: string, v: string) => setEdits((e) => ({ ...e, [key]: v }));

  const dirty = useMemo(() => {
    if (!read) return false;
    const byKey = new Map(read.settings.map((s) => [s.key, s.value]));
    return Object.entries(edits).some(([k, v]) => (byKey.get(k) ?? "") !== v);
  }, [edits, read]);

  const doWrite = async (changes: Record<string, string>) => {
    setSaving(true);
    setNotes([]);
    try {
      const result = await api.configWrite(changes);
      if (result.ok) {
        setErrors({});
        setWarnings(toIssueMap(result.warnings));
        setNotes(result.notes);
        setEdits({});
        setSavedOnce(true);
        await load();
      } else {
        // 7.3 — keep the operator's entered values, show the reason per setting.
        setErrors(toIssueMap(result.errors));
        setWarnings(toIssueMap(result.warnings));
      }
    } catch (e) {
      setErrors({ _: e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e) });
    } finally {
      setSaving(false);
    }
  };

  const save = () => doWrite(edits);

  const savingBlocked = maintenance !== null || stale;

  if (loadError && !read) {
    return (
      <section className="section configuration">
        <h1>Configuration</h1>
        <div className="panel is-error" role="alert">
          Could not load configuration: {loadError}
        </div>
      </section>
    );
  }

  return (
    <section className={`section configuration${stale ? " is-stale" : ""}`}>
      <h1>Configuration</h1>

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

      {read && <PendingPanel read={read} running={running} onRestarted={load} />}

      {savedOnce && notes.length > 0 && (
        <div className="panel is-warn" role="status">
          {notes.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      )}
      {savedOnce && Object.keys(errors).length === 0 && (
        <div className="ok" role="status">
          Saved.
        </div>
      )}

      {errors._ && <div className="controls-error">{errors._}</div>}

      <div className="panel">
        <h2>Settings</h2>
        {!read ? (
          <p className="muted">Loading…</p>
        ) : (
          <div className="cfg-list">
            {read.settings.map((s) =>
              s.key === LEVEL_KEY && worlds ? (
                <LevelPicker
                  key={s.key}
                  worlds={worlds}
                  value={valueFor(s.key, s.value)}
                  disabled={savingBlocked}
                  onChange={(v) => setEdit(s.key, v)}
                  onCreateAndSave={(name) => doWrite({ ...edits, [LEVEL_KEY]: name })}
                />
              ) : (
                <SettingRow
                  key={s.key}
                  setting={s}
                  value={valueFor(s.key, s.value)}
                  error={errors[s.key]}
                  warning={warnings[s.key]}
                  onChange={(v) => setEdit(s.key, v)}
                />
              ),
            )}
          </div>
        )}

        <div className="controls-row">
          <button
            className="btn btn-start"
            disabled={savingBlocked || saving || !dirty}
            onClick={save}
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
          {dirty && !savingBlocked && (
            <button className="link" disabled={saving} onClick={() => setEdits({})}>
              discard
            </button>
          )}
          {savingBlocked && maintenance && (
            <span className="controls-status">
              Settings are read-only during maintenance.
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
