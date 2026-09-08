import { useEffect, useState } from "react";
import { useStatus } from "../api/StatusContext";
import { usePlayers } from "../api/usePlayers";
import {
  api,
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
}: {
  player: RosterPlayer;
  selected: boolean;
  onSelect: () => void;
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

export function Players() {
  const { connected } = useStatus();
  const { roster, loading, error } = usePlayers();
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
                selected={selected === p.xuid}
                onSelect={() => setSelected(selected === p.xuid ? null : p.xuid)}
              />
            ))}
          </ul>
        </div>
      )}

      {loading && !roster && <p className="muted">Loading…</p>}

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
    </section>
  );
}
