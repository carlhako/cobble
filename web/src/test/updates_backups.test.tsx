import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UpdatesBackups } from "../sections/UpdatesBackups";
import { sections } from "../sections";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

function push(data: unknown) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() => es.emit(data));
}

const BASE = {
  run_state: "running",
  version: "1.0.0.1",
  uptime_seconds: 10,
  online_players: [],
  players_incomplete: false,
  last_shutdown: null,
  bootstrap: "done",
  bootstrap_detail: "",
  last_crash: null,
  maintenance: null,
  version_info: { installed: "1.0.0.1", available: null, up_to_date: null },
  update: {
    last_check_at: null,
    last_result: null,
    next_scheduled_at: "2026-06-02T04:00:00",
    skipping: null,
    terminal: false,
  },
  backup: {
    last_at: null,
    last_ok: null,
    next_scheduled_at: null,
    unhealthy: null,
    count: 0,
  },
};

function mockFetch(routes: Record<string, unknown>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const body = routes[key] ?? routes[url];
    if (body === undefined) return new Response("{}", { status: 200 });
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Updates & Backups section", () => {
  it("10.1 is registered as a section without any shell change", () => {
    expect(sections.map((s) => s.path)).toContain("/updates");
    expect(sections.find((s) => s.path === "/updates")?.label).toBe("Updates & Backups");
  });

  it("10.2 shows installed/available versions and an up-to-date state", async () => {
    mockFetch({ "GET /api/backups": { backups: [], unhealthy: null } });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({
      ...BASE,
      version_info: { installed: "1.0.0.1", available: "2.0.0.1", up_to_date: false },
    });
    expect(await screen.findByText("Update pending")).toBeInTheDocument();
    expect(screen.getByText("Installed").nextSibling).toHaveTextContent("1.0.0.1");
    expect(screen.getByText("Available").nextSibling).toHaveTextContent("2.0.0.1");
  });

  it("10.2 a check action's result is reflected from the pushed status, no refresh", async () => {
    mockFetch({
      "POST /api/updates/check": {
        installed: "1.0.0.1",
        available: "2.0.0.1",
        up_to_date: false,
        skipped: false,
        skipped_reason: null,
        error: null,
      },
      "GET /api/backups": { backups: [], unhealthy: null },
    });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);
    await userEvent.click(screen.getByRole("button", { name: "Check for updates" }));
    expect(await screen.findByText(/Update available: 2\.0\.0\.1/)).toBeInTheDocument();

    // the SSE stream then carries the new available version
    push({
      ...BASE,
      version_info: { installed: "1.0.0.1", available: "2.0.0.1", up_to_date: false },
    });
    expect(await screen.findByText("Update pending")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update to 2.0.0.1" })).toBeInTheDocument();
  });

  it("10.3 presents a failed update with version, step and captured output", async () => {
    mockFetch({
      "GET /api/backups": { backups: [], unhealthy: null },
      "GET /api/updates/diagnostics": {
        diagnostics: {
          version: "2.0.0.1",
          step: "readiness",
          status: "rolled_back",
          detail: "did not become ready",
          output: "[ERROR] boot failed on line 42",
          at: "2026-06-01T04:05:00",
        },
      },
    });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({
      ...BASE,
      update: {
        ...BASE.update,
        last_result: {
          status: "rolled_back",
          at: "2026-06-01T04:05:00",
          detail: "update to 2.0.0.1 failed",
          from_version: "2.0.0.1",
          to_version: "2.0.0.1",
          step: "readiness",
        },
      },
    });
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/rolled back/i)).toBeInTheDocument();
    expect(within(alert).getByText(/readiness/)).toBeInTheDocument();
    await userEvent.click(
      within(alert).getByRole("button", { name: /captured output/i }),
    );
    expect(await screen.findByLabelText("captured update output")).toHaveTextContent(
      "boot failed on line 42",
    );
  });

  it("10.4 shows the skipped-version notice and clears it on request", async () => {
    const fetchFn = mockFetch({
      "GET /api/backups": { backups: [], unhealthy: null },
      "POST /api/updates/clear-failed": { cleared: ["2.0.0.1"] },
    });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({
      ...BASE,
      version_info: { installed: "1.0.0.1", available: "2.0.0.1", up_to_date: false },
      update: { ...BASE.update, skipping: "2.0.0.1" },
    });
    expect(
      await screen.findByText(/will not be retried automatically/),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear record" }));
    await waitFor(() =>
      expect(fetchFn).toHaveBeenCalledWith(
        "/api/updates/clear-failed",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText(/may be attempted again/)).toBeInTheDocument();
  });

  it("10.5 presents the rollback-failed state as needing intervention, visually distinct", async () => {
    mockFetch({ "GET /api/backups": { backups: [], unhealthy: null } });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE, update: { ...BASE.update, terminal: true } });
    const alert = await screen.findByText(/operator intervention required/i);
    expect(alert.closest(".panel")).toHaveClass("is-critical");
  });

  it("10.6 restore is gated by a confirmation naming the backup and stating replacement", async () => {
    const fetchFn = mockFetch({
      "GET /api/backups": {
        backups: [
          {
            archive: "cobble-backup-20260601T040000.000000Z.tar.gz",
            captured_at: "2026-06-01T04:00:00",
            bedrock_version: "1.0.0.1",
            shutdown_clean: true,
            size_bytes: 2048,
            restorable: true,
            reason: null,
          },
        ],
        unhealthy: null,
      },
      "POST /api/backups/cobble-backup-20260601T040000.000000Z.tar.gz/restore": {
        ok: true,
        at: "x",
        archive: "cobble-backup-20260601T040000.000000Z.tar.gz",
        replaced_capture: "cobble-backup-later.tar.gz",
        needs_confirmation: false,
        warning: null,
        error: null,
      },
    });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);

    expect(await screen.findByText("1.0.0.1", { selector: "td" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));

    const dialog = await screen.findByRole("alertdialog", { name: "confirm restore" });
    expect(within(dialog).getByText(/cobble-backup-20260601T040000/)).toBeInTheDocument();
    expect(within(dialog).getByText(/replaces the current world/i)).toBeInTheDocument();

    // no restore call has been made yet — only the confirm is showing
    expect(fetchFn).not.toHaveBeenCalledWith(
      expect.stringContaining("/restore"),
      expect.anything(),
    );

    await userEvent.click(
      within(dialog).getByRole("button", { name: /replace current state and restore/i }),
    );
    await waitFor(() =>
      expect(fetchFn).toHaveBeenCalledWith(
        expect.stringContaining("/restore"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("10.7 reflects a maintenance operation and withholds nothing conflicting here", async () => {
    mockFetch({ "GET /api/backups": { backups: [], unhealthy: null } });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE, maintenance: { operation: "updating", step: "activating 2.0.0.1" } });
    expect(await screen.findByText("Update in progress")).toBeInTheDocument();
    expect(screen.getByText(/activating 2\.0\.0\.1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check for updates" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Capture backup now" })).toBeDisabled();
  });

  it("10.8 presents an unhealthy backup condition with its reason", async () => {
    mockFetch({
      "GET /api/backups": {
        backups: [],
        unhealthy: "backup destination is not writable",
      },
    });
    renderApp(<UpdatesBackups />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({
      ...BASE,
      backup: { ...BASE.backup, unhealthy: "backup destination is not writable" },
    });
    expect(await screen.findByText("Backups are failing.")).toBeInTheDocument();
    expect(screen.getByText(/not writable/)).toBeInTheDocument();
  });
});
