import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TransportView } from "../api/client";
import { Dashboard } from "../sections/Dashboard";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

const RUNNING = {
  run_state: "running",
  version: "1.26.51.1",
  uptime_seconds: 60,
  online_players: [],
  players_incomplete: false,
  last_shutdown: null,
  config: { pending: false, pending_count: 0 },
};

function transport(over: Partial<TransportView> = {}): TransportView {
  return {
    value: "nethernet",
    saved: "nethernet",
    recommended: "nethernet",
    is_recommended: true,
    running: true,
    pending_restart: false,
    ...over,
  };
}

const RAKNET = transport({ value: "raknet", saved: "raknet", is_recommended: false });

/** Serves GET /api/config/transport as views[0], then views[1] once the switch
 *  is saved, then views[2] once the server is restarted, and records every call. */
function mockFetch(views: TransportView[]) {
  const calls: string[] = [];
  let stage = 0;
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    calls.push(key);
    if (key === "POST /api/config") stage = Math.max(stage, 1);
    if (key === "POST /api/server/restart") stage = 2;
    let body: unknown = {};
    if (key === "GET /api/config/transport")
      body = views[Math.min(stage, views.length - 1)];
    if (key === "POST /api/config")
      body = {
        ok: true,
        errors: [],
        warnings: [],
        changed: ["transport"],
        notes: [],
        pending: [],
      };
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

async function renderRunning() {
  renderApp(<Dashboard />);
  await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
  act(() => FakeEventSource.byUrl("/api/status/stream")!.emit(RUNNING));
}

afterEach(() => vi.unstubAllGlobals());

describe("dashboard transport", () => {
  it("shows the transport in use, with no notice when it is the recommended one", async () => {
    mockFetch([transport()]);
    await renderRunning();
    const card = (await screen.findByText("Transport")).closest(".card") as HTMLElement;
    expect(await within(card).findByText("nethernet")).toBeInTheDocument();
    expect(screen.queryByText(/not the recommended transport/)).toBeNull();
  });

  it("warns on a transport that is not the version's default and switches it", async () => {
    const { fn, calls } = mockFetch([
      RAKNET,
      transport({
        value: "raknet",
        saved: "nethernet",
        is_recommended: false,
        pending_restart: true,
      }),
      transport(),
    ]);
    await renderRunning();

    const notice = await screen.findByText(/raknet is not the recommended transport/);
    expect(notice.closest(".panel")).toHaveTextContent(
      "Players may not be able to see or join the server",
    );
    const card = screen.getByText("Transport").closest(".card") as HTMLElement;
    expect(within(card).getByText("raknet")).toHaveClass("warn");

    await userEvent.click(screen.getByRole("button", { name: "Switch to nethernet" }));
    const write = fn.mock.calls.find(
      ([u, init]) => u === "/api/config" && init?.method === "POST",
    );
    expect(JSON.parse(String(write?.[1]?.body))).toEqual({
      changes: { transport: "nethernet" },
    });

    // Saved but still running raknet: the notice now offers the restart.
    expect(await screen.findByText(/Switched to nethernet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restart now" }));
    expect(calls).toContain("POST /api/server/restart");
    await waitFor(() => expect(screen.queryByText(/Switched to nethernet/)).toBeNull());
  });

  it("names a saved non-default transport before a restart applies it", async () => {
    mockFetch([
      transport({ saved: "raknet", is_recommended: false, pending_restart: true }),
    ]);
    await renderRunning();
    expect(
      await screen.findByText(/raknet is not the recommended transport/),
    ).toBeInTheDocument();
    // The card shows what is running, which is still fine.
    const card = screen.getByText("Transport").closest(".card") as HTMLElement;
    expect(within(card).getByText("nethernet")).not.toHaveClass("warn");
  });

  it("gives no advice when the recommended transport is unknown", async () => {
    mockFetch([transport({ value: "raknet", recommended: null, is_recommended: true })]);
    await renderRunning();
    expect(await screen.findByText("raknet")).toBeInTheDocument();
    expect(screen.queryByText(/not the recommended transport/)).toBeNull();
  });
});
