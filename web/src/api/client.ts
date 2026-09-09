// Thin HTTP client for the cobble programmatic interface. The web interface has
// no privileged path: every state change is one of these calls (web-ui-shell).

export interface ApiError {
  error: string;
  detail: string;
}

export class ApiCallError extends Error {
  code: string;
  /** The structured error body, when the server sent one (e.g. a ban's
   *  `would_exclude` list on a `confirmation_required` refusal). */
  body: Record<string, unknown> | null;
  constructor(code: string, detail: string, body: Record<string, unknown> | null = null) {
    super(detail || code);
    this.code = code;
    this.body = body;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) {
    let code = `http_${resp.status}`;
    let detail = resp.statusText;
    let body: Record<string, unknown> | null = null;
    try {
      const data = (await resp.json()) as {
        detail?: (ApiError & Record<string, unknown>) | string;
      };
      if (data.detail && typeof data.detail === "object") {
        code = data.detail.error;
        detail = data.detail.detail;
        body = data.detail;
      } else if (typeof data.detail === "string") {
        detail = data.detail;
      }
    } catch {
      // non-JSON error body; keep the defaults
    }
    throw new ApiCallError(code, detail, body);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export interface UpdateCheckResult {
  installed: string | null;
  available: string | null;
  up_to_date: boolean;
  skipped: boolean;
  skipped_reason: string | null;
  error: string | null;
}

export interface UpdateResult {
  ok: boolean;
  status: "success" | "up_to_date" | "skipped" | "aborted" | "rolled_back" | "terminal";
  detail: string;
  from_version: string | null;
  to_version: string | null;
  step: string | null;
  rolled_back: boolean;
  terminal: boolean;
}

export interface UpdateDiagnostics {
  version: string | null;
  step: string | null;
  status: string;
  detail: string;
  output: string;
  at: string;
}

export interface BackupEntry {
  archive: string;
  captured_at: string | null;
  bedrock_version: string | null;
  shutdown_clean: boolean | null;
  size_bytes: number;
  restorable: boolean;
  reason: string | null;
}

export interface RestoreResult {
  ok: boolean;
  at: string;
  archive: string;
  replaced_capture: string | null;
  needs_confirmation: boolean;
  warning: string | null;
  error: string | null;
}

export type PropertyType = "bool" | "int" | "float" | "enum" | "string";

export interface PropertySchema {
  key: string;
  type: PropertyType;
  default: string;
  description: string;
  members: string[] | null;
  minimum: number | null;
  maximum: number | null;
}

export interface ConfigSetting {
  key: string;
  value: string;
  recognised: boolean;
  schema: PropertySchema | null;
}

export interface PendingChange {
  key: string;
  saved: string | null;
  in_effect: string | null;
}

export interface ValidationIssue {
  key: string;
  severity: "error" | "warning";
  message: string;
}

export interface ConfigRead {
  settings: ConfigSetting[];
  pending: PendingChange[];
}

export interface ConfigWriteResult {
  ok: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  changed: string[];
  notes: string[];
  pending: PendingChange[];
}

export type SessionEndReason =
  "observed" | "server_stop" | "server_exit" | "reconstructed" | "kicked" | null;

export interface RosterPlayer {
  xuid: string;
  gamertag: string;
  total_playtime_seconds: number;
  session_count: number;
  first_seen: string;
  last_seen: string;
  online: boolean;
  /** True when the total includes one or more reconstructed session ends. */
  approximate: boolean;
}

export interface Roster {
  players: RosterPlayer[];
  /** ISO date from which history has been recorded, or null if nothing yet. */
  recorded_since: string | null;
}

export interface PlayerSession {
  connected_at: string;
  spawned_at: string | null;
  disconnected_at: string | null;
  duration_seconds: number;
  end_reason: SessionEndReason;
  in_progress: boolean;
  /** True when this session's end time was reconstructed, not observed. */
  approximate: boolean;
}

export interface PlayerSessions {
  xuid: string;
  gamertag: string;
  sessions: PlayerSession[];
}

export interface WorldInfo {
  name: string;
  is_current: boolean;
}

export interface WorldsView {
  worlds: WorldInfo[];
  current: string;
  current_present: boolean;
}

// --- Gamerules (M5) -------------------------------------------------
export type GameruleType = "bool" | "int" | "enum" | null;
export type GameruleValue = boolean | number | string;

export interface GameruleRow {
  name: string;
  raw: string;
  value: GameruleValue;
  type: GameruleType;
  recognised: boolean;
  minimum?: number | null;
  maximum?: number | null;
  members?: string[];
  description?: string;
  default?: GameruleValue;
}

export type GameruleLiveness = "live" | "recorded" | "unread";
export type GameruleReportKind = "adoption" | "repair" | "defaults";

export interface GameruleReport {
  level_name: string;
  kind: GameruleReportKind;
  created_at: string;
  rules: Record<string, GameruleValue>;
}

export interface GameruleView {
  level_name: string;
  liveness: GameruleLiveness;
  sampled_at: string | null;
  rules: GameruleRow[];
  report: GameruleReport | null;
}

export interface GameruleWriteResult {
  queued: boolean;
  level_name: string;
  rule?: GameruleRow | null;
  rules?: GameruleRow[];
  pending?: Record<string, GameruleValue>;
  detail?: string;
}

export interface GameruleCatalogueEntry {
  name: string;
  type: Exclude<GameruleType, null>;
  default: GameruleValue;
  description: string;
  minimum: number | null;
  maximum: number | null;
  members: string[];
}

export interface GameruleDefaults {
  defaults: Record<string, GameruleValue>;
  catalogue: GameruleCatalogueEntry[];
}

// --- Access control (M6) -----------------------------------------
export type PermissionLevel = "visitor" | "member" | "operator";

export interface AllowlistEntry {
  name: string;
  xuid: string | null;
  has_identifier: boolean;
  has_played: boolean;
}

export interface PermissionRecord {
  xuid: string;
  level: PermissionLevel;
  name: string | null;
}

export interface BanRecordApi {
  xuid: string;
  name: string;
  reason: string;
  banned_at: string;
  lifted_at: string | null;
  active: boolean;
}

export interface EnforcementView {
  saved: boolean;
  in_effect: "on" | "off" | "unknown";
  running: boolean;
  disagreement: boolean;
}

export interface AccessRead {
  allowlist: { readable: boolean; entries: AllowlistEntry[] };
  permissions: PermissionRecord[];
  enforcement: EnforcementView;
  bans: BanRecordApi[];
}

export interface KickResultApi {
  xuid: string;
  command: string;
  confirmed: boolean;
  unconfirmed: boolean;
  no_target: boolean;
}

export interface BanResultApi {
  xuid: string;
  name: string;
  needs_confirmation: boolean;
  would_exclude: string[];
  steps: string[];
  kick: KickResultApi | null;
  identifier_written: boolean;
}

export interface UnbanResultApi {
  xuid: string;
  name: string;
  steps: string[];
}

/** 409 body when a ban would enable enforcement (task 9.3). */
export interface BanConfirmationRequired {
  error: "confirmation_required";
  detail: string;
  would_exclude: string[];
}

export const api = {
  start: () => request<StatusPayload>("POST", "/server/start"),
  stop: () => request<StatusPayload>("POST", "/server/stop"),
  restart: () => request<StatusPayload>("POST", "/server/restart"),
  bootstrap: () => request<StatusPayload>("POST", "/server/bootstrap"),
  status: () => request<StatusPayload>("GET", "/status"),
  sendCommand: (command: string) =>
    request<void>("POST", "/console/command", { command }),

  updatesCheck: () => request<UpdateCheckResult>("POST", "/updates/check"),
  updatesApply: () => request<UpdateResult>("POST", "/updates/apply"),
  updatesClearFailed: (version?: string) =>
    request<{ cleared: string[] }>("POST", "/updates/clear-failed", {
      version: version ?? null,
    }),
  updatesDiagnostics: () =>
    request<{ diagnostics: UpdateDiagnostics | null }>("GET", "/updates/diagnostics"),

  backupsList: () =>
    request<{ backups: BackupEntry[]; unhealthy: string | null }>("GET", "/backups"),
  backupsCapture: () =>
    request<{ ok: boolean; error: string | null }>("POST", "/backups"),
  backupsRestore: (archive: string, confirmOldVersion = false) =>
    request<RestoreResult>("POST", `/backups/${encodeURIComponent(archive)}/restore`, {
      confirm_old_version: confirmOldVersion,
    }),
  /** URL that serves a held backup as a downloadable file (plain GET, no side
   *  effect). Used as an <a href> rather than a fetch so the browser saves it. */
  backupsDownloadUrl: (archive: string) => `/api/backups/${encodeURIComponent(archive)}`,

  players: () => request<Roster>("GET", "/players"),
  playerSessions: (xuid: string) =>
    request<PlayerSessions>("GET", `/players/${encodeURIComponent(xuid)}/sessions`),

  configRead: () => request<ConfigRead>("GET", "/config"),
  configWrite: (changes: Record<string, string>) =>
    request<ConfigWriteResult>("POST", "/config", { changes }),
  configWorlds: () => request<WorldsView>("GET", "/config/worlds"),

  gamerulesRead: () => request<GameruleView>("GET", "/gamerules"),
  gamerulesWrite: (name: string, value: GameruleValue) =>
    request<GameruleWriteResult>("POST", "/gamerules", { name, value }),
  gamerulesDefaults: () => request<GameruleDefaults>("GET", "/gamerules/defaults"),
  gamerulesSetDefault: (name: string, value: GameruleValue) =>
    request<GameruleDefaults>("PUT", "/gamerules/defaults", { name, value }),
  gamerulesClearDefault: (name: string) =>
    request<GameruleDefaults>(
      "DELETE",
      `/gamerules/defaults/${encodeURIComponent(name)}`,
    ),
  gamerulesAcknowledge: () => request<{ ok: boolean }>("POST", "/gamerules/acknowledge"),

  accessRead: () => request<AccessRead>("GET", "/access"),
  accessAllowlistAdd: (name: string) =>
    request<{ entry: AllowlistEntry }>("POST", "/access/allowlist", { name }),
  accessAllowlistRemove: (opts: { name?: string; xuid?: string }) => {
    const q = new URLSearchParams();
    if (opts.name) q.set("name", opts.name);
    if (opts.xuid) q.set("xuid", opts.xuid);
    return request<{ removed: boolean }>("DELETE", `/access/allowlist?${q.toString()}`);
  },
  accessPermissionsSet: (xuid: string, level: PermissionLevel) =>
    request<{ xuid: string; level: PermissionLevel; reloaded: boolean }>(
      "POST",
      "/access/permissions",
      { xuid, level },
    ),
  accessEnforcementSet: (enabled: boolean) =>
    request<{ ok: boolean; enforcement: EnforcementView }>(
      "POST",
      "/access/enforcement",
      {
        enabled,
      },
    ),

  playerKick: (xuid: string, reason = "") =>
    request<KickResultApi>("POST", `/players/${encodeURIComponent(xuid)}/kick`, {
      reason,
    }),
  playerBan: (
    xuid: string,
    opts: { reason?: string; confirm?: boolean; permit_excluded?: boolean } = {},
  ) =>
    request<BanResultApi>("POST", `/players/${encodeURIComponent(xuid)}/ban`, {
      reason: opts.reason ?? "",
      confirm: opts.confirm ?? false,
      permit_excluded: opts.permit_excluded ?? false,
    }),
  playerUnban: (xuid: string) =>
    request<UnbanResultApi>("POST", `/players/${encodeURIComponent(xuid)}/unban`),
};

export type BootstrapState = "skipped" | "not_needed" | "running" | "done" | "failed";

export type RunState =
  | "stopped"
  | "starting"
  | "running"
  | "stopping"
  | "crashed"
  | "failed"
  | "recovery_abandoned";

export interface OnlinePlayer {
  xuid: string;
  gamertag: string;
}

export interface MaintenanceInfo {
  operation: "updating" | "restoring" | "backing_up";
  step: string | null;
}

export interface VersionInfo {
  installed: string | null;
  available: string | null;
  up_to_date: boolean | null;
}

export interface UpdateInfo {
  last_check_at: string | null;
  last_result: {
    status: string;
    at: string;
    detail: string;
    from_version: string | null;
    to_version: string | null;
    step: string | null;
  } | null;
  next_scheduled_at: string | null;
  skipping: string | null;
  terminal: boolean;
}

export interface BackupInfo {
  last_at: string | null;
  last_ok: boolean | null;
  next_scheduled_at: string | null;
  unhealthy: string | null;
  count: number;
}

export interface StatusPayload {
  run_state: RunState;
  version: string | null;
  uptime_seconds: number | null;
  online_players: OnlinePlayer[];
  players_incomplete: boolean;
  last_shutdown: { clean: boolean; at: string } | null;
  bootstrap: BootstrapState;
  bootstrap_detail: string;
  last_crash: {
    exit_code: number | null;
    at: string;
    recovery: "none" | "restarting" | "running" | "abandoned" | "stopped";
  } | null;
  maintenance: MaintenanceInfo | null;
  version_info: VersionInfo | null;
  update: UpdateInfo | null;
  backup: BackupInfo | null;
  config: { pending: boolean; pending_count: number } | null;
  gamerules: {
    active_world: string;
    liveness: GameruleLiveness;
    last_read_at: string | null;
    report: GameruleReport | null;
  } | null;
  access: {
    running: boolean;
    in_effect: "on" | "off" | "unknown";
    saved: boolean | null;
    disagreement: boolean;
    ban_count: number;
  } | null;
}
