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

export const api = {
  start: () => request<StatusPayload>("POST", "/server/start"),
  stop: () => request<StatusPayload>("POST", "/server/stop"),
  restart: () => request<StatusPayload>("POST", "/server/restart"),
  bootstrap: () => request<StatusPayload>("POST", "/server/bootstrap"),
  status: () => request<StatusPayload>("GET", "/status"),
  sendCommand: (command: string) =>
    request<void>("POST", "/console/command", { command }),
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

export interface StatusPayload {
  run_state: RunState;
  version: string | null;
  uptime_seconds: number | null;
  online_players: OnlinePlayer[];
  players_incomplete: boolean;
  last_shutdown: { clean: boolean; at: string } | null;
  bootstrap: BootstrapState;
  bootstrap_detail: string;
}
