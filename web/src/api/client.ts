// Thin HTTP client for the cobble programmatic interface. The web interface has
// no privileged path: every state change is one of these calls (web-ui-shell).

export interface ApiError {
  error: string;
  detail: string;
}

export class ApiCallError extends Error {
  code: string;
  constructor(code: string, detail: string) {
    super(detail || code);
    this.code = code;
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
    try {
      const data = (await resp.json()) as { detail?: ApiError | string };
      if (data.detail && typeof data.detail === "object") {
        code = data.detail.error;
        detail = data.detail.detail;
      } else if (typeof data.detail === "string") {
        detail = data.detail;
      }
    } catch {
      // non-JSON error body; keep the defaults
    }
    throw new ApiCallError(code, detail);
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

export type PropertyType = "bool" | "int" | "enum" | "string";

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

export interface WorldInfo {
  name: string;
  is_current: boolean;
}

export interface WorldsView {
  worlds: WorldInfo[];
  current: string;
  current_present: boolean;
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

  configRead: () => request<ConfigRead>("GET", "/config"),
  configWrite: (changes: Record<string, string>) =>
    request<ConfigWriteResult>("POST", "/config", { changes }),
  configWorlds: () => request<WorldsView>("GET", "/config/worlds"),
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
}
