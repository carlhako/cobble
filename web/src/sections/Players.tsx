import { useEffect, useMemo, useState } from "react";
import { useStatus } from "../api/StatusContext";
import { usePlayers } from "../api/usePlayers";
import { useAccess } from "../api/useAccess";
import {
  api,
  ApiCallError,
  type AccessRead,
  type PermissionLevel,
  type PlayerSession,
  type PlayerSessions,
  type RosterPlayer,
  type SessionEndReason,
} from "../api/client";

function formatDuration(seconds: number): string {
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return [d && `${d}d`, h && `${h}h`, m && `${m}m`].filter(Boolean).join(" ") || "0m";
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

const END_REASON_LABEL: Record<Exclude<SessionEndReason, null>, string> = {
  observed: "left",
  server_stop: "server stopped",
  server_exit: "server exited unexpectedly",
  reconstructed: "end time reconstructed after cobble restarted",
  kicked: "kicked",
};

function endReasonText(s: PlayerSession): string {
  if (s.in_progress) return "in progress";
  return s.end_reason ? END_REASON_LABEL[s.end_reason] : "ended";
}

function SessionList({ data }: { data: PlayerSessions }) {
  if (data.sessions.length === 0) {
    return <p className="muted">No sessions recorded for this player.</p>;
  }
  return (
    <ul className="player-list session-list">
      {data.sessions.map((s, i) => (
        <li key={`${s.connected_at}-${i}`}>
          <span>{formatWhen(s.connected_at)}</span>
          <span>
            {s.approximate ? "~" : ""}
            {formatDuration(s.duration_seconds)}
            {s.approximate && (
              <span className="badge badge-warn" title={endReasonText(s)}>
                approx
              </span>
            )}
          </span>
          <span className="xuid">{endReasonText(s)}</span>
        </li>
      ))}
    </ul>
  );
}

function RosterRow({
  player,
  selected,
  onSelect,
  banned,
}: {
  player: RosterPlayer;
  selected: boolean;
  onSelect: () => void;
  banned: boolean;
}) {
  return (
    <li className={player.online ? "is-online" : undefined}>
      <button
        type="button"
        className={`roster-row${selected ? " is-selected" : ""}`}
        aria-pressed={selected}
        onClick={onSelect}
      >
        <span className="gamertag">
          {player.gamertag || "(unknown)"}
          {player.online && (
            <span className="badge badge-online" title="currently online">
              online
            </span>
          )}
          {banned && (
            <span className="badge badge-warn" title="this player is banned">
              banned
            </span>
          )}
        </span>
        <span>
          {player.approximate ? "~" : ""}
          {formatDuration(player.total_playtime_seconds)}
          {player.approximate && (
            <span
              className="badge badge-warn"
              title="includes one or more sessions whose end time was reconstructed"
            >
              approx
            </span>
          )}
        </span>
        <span className="xuid">
          {player.session_count} session{player.session_count === 1 ? "" : "s"} · last
          seen {formatWhen(player.last_seen)}
        </span>
      </button>
    </li>
  );
}

// --- enforcement (task 9.5) ---------------------------------------
function EnforcementPanel({ access }: { access: AccessRead }) {
  const e = access.enforcement;
  const savedText = e.saved === null ? "unknown" : e.saved ? "enforced" : "not enforced";
  if (!e.running) {
    return (
      <p className="muted" data-testid="enforcement">
        Server stopped. The next start will apply: <strong>{savedText}</strong>{" "}
        (allowlist). The live enforcement state is not observable while the server is
        stopped.
      </p>
    );
  }
  if (e.in_effect === "unknown") {
    return (
      <p className="muted" data-testid="enforcement">
        Allowlist enforcement: <strong>unknown</strong> — cobble has not yet observed the
        running server report it. Saved setting: {savedText}.
      </p>
    );
  }
  if (e.disagreement) {
    return (
      <p className="panel is-error" role="status" data-testid="enforcement">
        Allowlist enforcement disagrees with the saved setting. In effect now:{" "}
        <strong>{e.in_effect === "on" ? "enforced" : "not enforced"}</strong>. Saved:{" "}
        {savedText}. The value in effect now is what the running server is applying.
      </p>
    );
  }
  return (
    <p className="muted" data-testid="enforcement">
      Allowlist enforcement:{" "}
      <strong>{e.in_effect === "on" ? "enforced" : "not enforced"}</strong> (matches the
      saved setting).
    </p>
  );
}

// --- allowlist + permissions views (task 9.4) --------------------
function AllowlistPanel({ access }: { access: AccessRead }) {
  if (!access.allowlist.readable) {
    return (
      <div className="panel is-error" role="alert">
        allowlist.json could not be read.
      </div>
    );
  }
  return (
    <div className="panel" data-testid="allowlist-view">
      <h2>Allowlist</h2>
      {access.allowlist.entries.length === 0 ? (
        <p className="muted">The allowlist is empty.</p>
      ) : (
        <ul className="player-list">
          {access.allowlist.entries.map((entry) => (
            <li key={`${entry.name}-${entry.xuid ?? "noid"}`}>
              <span className="gamertag">{entry.name}</span>
              <span className="xuid">
                {entry.has_identifier ? entry.xuid : "identified by name only"}
              </span>
              <span>
                {!entry.has_played && (
                  <span className="badge" title="has never played on this server">
                    never played here
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <h2>Operator permissions</h2>
      {access.permissions.length === 0 ? (
        <p className="muted">No permission records.</p>
      ) : (
        <ul className="player-list" data-testid="permissions-view">
          {access.permissions.map((p) => (
            <li key={p.xuid}>
              <span className="gamertag">{p.name ?? "(name unknown)"}</span>
              <span className="xuid">{p.xuid}</span>
              <span>{p.level}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface PlayerAccess {
  banned: boolean;
  banReason: string | null;
  bannedAt: string | null;
  onAllowlist: boolean;
  level: PermissionLevel;
}

function derivePlayerAccess(
  player: RosterPlayer,
  access: AccessRead | null,
): PlayerAccess {
  if (!access) {
    return {
      banned: false,
      banReason: null,
      bannedAt: null,
      onAllowlist: false,
      level: "member",
    };
  }
  const ban = access.bans.find((b) => b.xuid === player.xuid && b.active);
  const onAllowlist = access.allowlist.entries.some(
    (e) =>
      (e.xuid && e.xuid === player.xuid) ||
      e.name.toLowerCase() === player.gamertag.toLowerCase(),
  );
  const perm = access.permissions.find((p) => p.xuid === player.xuid);
  return {
    banned: Boolean(ban),
    banReason: ban?.reason ?? null,
    bannedAt: ban?.banned_at ?? null,
    onAllowlist,
    level: perm?.level ?? "member",
  };
}

const LEVELS: PermissionLevel[] = ["visitor", "member", "operator"];

function PlayerAccessPanel({
  player,
  access,
  enforced,
  serverRunning,
  maintenance,
  onDone,
}: {
  player: RosterPlayer;
  access: AccessRead | null;
  enforced: boolean;
  serverRunning: boolean;
  maintenance: string | null;
  onDone: () => void;
}) {
  const pa = derivePlayerAccess(player, access);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ wouldExclude: string[] } | null>(null);

  // Reset transient UI when the selected player changes.
  useEffect(() => {
    setError(null);
    setNote(null);
    setConfirm(null);
  }, [player.xuid]);

  const disabled = maintenance !== null || busy !== null;
  const kickDisabled = disabled || !player.online || !serverRunning;

  async function run(label: string, fn: () => Promise<string>) {
    setBusy(label);
    setError(null);
    setNote(null);
    try {
      const message = await fn();
      setNote(message);
      onDone();
    } catch (e) {
      if (e instanceof ApiCallError) setError(`${e.message}`);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function doBan(opts: { confirm?: boolean; permitExcluded?: boolean }) {
    setBusy("ban");
    setError(null);
    setNote(null);
    try {
      const r = await api.playerBan(player.xuid, {
        reason: "",
        confirm: opts.confirm,
        permit_excluded: opts.permitExcluded,
      });
      setConfirm(null);
      setNote(`Ban applied: ${r.steps.join(", ") || "no steps"}.`);
      onDone();
    } catch (e) {
      if (e instanceof ApiCallError && e.code === "confirmation_required") {
        const list = Array.isArray(e.body?.would_exclude)
          ? (e.body!.would_exclude as string[])
          : [];
        setConfirm({ wouldExclude: list });
      } else if (e instanceof ApiCallError) {
        setError(e.message);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel" data-testid="player-access">
      <h2>{player.gamertag || player.xuid} — access</h2>

      {maintenance !== null && (
        <p className="muted" role="status" data-testid="moderation-unavailable">
          Moderation is unavailable while a {maintenance} operation is in progress.
        </p>
      )}

      <ul className="player-list">
        <li>
          <span>Status</span>
          <span>
            {pa.banned ? (
              <span className="badge badge-warn">banned</span>
            ) : enforced ? (
              pa.onAllowlist ? (
                "permitted to join"
              ) : (
                "not permitted (allowlist enforced)"
              )
            ) : pa.onAllowlist ? (
              "on the allowlist (not currently enforced)"
            ) : (
              "not on the allowlist (allowlist not enforced)"
            )}
          </span>
        </li>
        {pa.banned && (
          <li data-testid="ban-detail">
            <span>Ban</span>
            <span>
              {pa.banReason ? `“${pa.banReason}”` : "(no reason given)"} ·{" "}
              {pa.bannedAt ? formatWhen(pa.bannedAt) : "unknown time"}
            </span>
          </li>
        )}
        <li>
          <span>Permission level</span>
          <span>
            <select
              aria-label="permission level"
              value={pa.level}
              disabled={disabled}
              onChange={(ev) => {
                const level = ev.target.value as PermissionLevel;
                void run("permission", async () => {
                  await api.accessPermissionsSet(player.xuid, level);
                  return `Permission level set to ${level}.`;
                });
              }}
            >
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </span>
        </li>
      </ul>

      <div className="controls-row">
        <button
          type="button"
          disabled={kickDisabled}
          title={
            !serverRunning
              ? "the server is not running"
              : !player.online
                ? "this player is not connected"
                : undefined
          }
          onClick={() =>
            void run("kick", async () => {
              const r = await api.playerKick(player.xuid);
              return r.confirmed
                ? "Kicked."
                : r.no_target
                  ? "The server could not find that player."
                  : "Kick sent; the disconnect was not confirmed.";
            })
          }
        >
          Kick
        </button>
        {pa.banned ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              void run("unban", async () => {
                const r = await api.playerUnban(player.xuid);
                return `Unbanned: ${r.steps.join(", ") || "no steps"}.`;
              })
            }
          >
            Unban
          </button>
        ) : (
          <button type="button" disabled={disabled} onClick={() => void doBan({})}>
            Ban
          </button>
        )}
      </div>

      {confirm && (
        <div
          className="panel is-warning"
          role="dialog"
          aria-label="confirm ban"
          data-testid="ban-confirm"
        >
          <p>
            Banning {player.gamertag || player.xuid} will turn on allowlist enforcement.
            That excludes every player not on the allowlist:
          </p>
          {confirm.wouldExclude.length > 0 ? (
            <ul>
              {confirm.wouldExclude.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">
              No other players who have played here would be excluded.
            </p>
          )}
          <div className="controls-row">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void doBan({ confirm: true, permitExcluded: true })}
            >
              Ban and add the players above to the allowlist
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void doBan({ confirm: true })}
            >
              Ban anyway (exclude them)
            </button>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => setConfirm(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="controls-error" role="alert" data-testid="player-action-error">
          {player.gamertag || player.xuid}: {error}
        </div>
      )}
      {note && (
        <p className="muted" role="status" data-testid="player-action-note">
          {note}
        </p>
      )}
    </div>
  );
}

export function Players() {
  const { connected, status } = useStatus();
  const { roster, loading, error } = usePlayers();
  const { access, reload: reloadAccess } = useAccess();
  const [selected, setSelected] = useState<string | null>(null);
  const [sessions, setSessions] = useState<PlayerSessions | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  useEffect(() => {
    if (selected === null) {
      setSessions(null);
      return;
    }
    let cancelled = false;
    setSessions(null);
    setSessionsError(null);
    api
      .playerSessions(selected)
      .then((d) => !cancelled && setSessions(d))
      .catch(
        (e) => !cancelled && setSessionsError(e instanceof Error ? e.message : String(e)),
      );
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const players = [...(roster?.players ?? [])].sort((a, b) =>
    a.last_seen < b.last_seen ? 1 : a.last_seen > b.last_seen ? -1 : 0,
  );
  const recordedSince = roster?.recorded_since ?? null;

  const serverRunning = status?.run_state === "running";
  const maintenance = status?.maintenance?.operation ?? null;
  const enforced = access?.enforcement.in_effect === "on";

  const bannedXuids = useMemo(
    () => new Set((access?.bans ?? []).filter((b) => b.active).map((b) => b.xuid)),
    [access],
  );

  const selectedPlayer = players.find((p) => p.xuid === selected) ?? null;

  return (
    <section className="section players">
      <h1>
        Players
        {!connected && <span className="badge badge-warn">disconnected</span>}
      </h1>

      {recordedSince && (
        <p className="muted" data-testid="recorded-since">
          History recorded since {formatWhen(recordedSince)}. Play before then was never
          recorded.
        </p>
      )}

      {error && (
        <div className="panel is-error" role="alert">
          Could not load the roster: {error}
        </div>
      )}

      {access && <EnforcementPanel access={access} />}

      {!error && roster && players.length === 0 && (
        <div className="panel" role="status">
          <strong>No player history yet.</strong>
          <p className="muted">
            No players have been observed since cobble began recording player history. Any
            earlier play was never recorded — this is not an error.
          </p>
        </div>
      )}

      {players.length > 0 && (
        <div className="panel">
          <ul className="player-list roster-list">
            {players.map((p) => (
              <RosterRow
                key={p.xuid}
                player={p}
                banned={bannedXuids.has(p.xuid)}
                selected={selected === p.xuid}
                onSelect={() => setSelected(selected === p.xuid ? null : p.xuid)}
              />
            ))}
          </ul>
        </div>
      )}

      {loading && !roster && <p className="muted">Loading…</p>}

      {selectedPlayer && (
        <PlayerAccessPanel
          player={selectedPlayer}
          access={access}
          enforced={enforced}
          serverRunning={serverRunning}
          maintenance={maintenance}
          onDone={reloadAccess}
        />
      )}

      {selected && (
        <div className="panel" data-testid="session-history">
          <h2>{sessions?.gamertag || selected} — sessions</h2>
          {sessionsError && (
            <div className="controls-error" role="alert">
              {sessionsError}
            </div>
          )}
          {sessions ? (
            <SessionList data={sessions} />
          ) : (
            !sessionsError && <p className="muted">Loading sessions…</p>
          )}
        </div>
      )}

      {access && <AllowlistPanel access={access} />}
    </section>
  );
}
