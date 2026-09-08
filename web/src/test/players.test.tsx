import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Players } from "../sections/Players";
import { sections } from "../sections";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

function push(data: unknown) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() => es.emit(data));
}

const BASE_STATUS = {
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
  version_info: null,
  update: null,
  backup: null,
  config: null,
};

const ALEX = {
  xuid: "alex",
  gamertag: "Alex",
  total_playtime_seconds: 7200,
  session_count: 3,
  first_seen: "2026-01-01T08:00:00+00:00",
  last_seen: "2026-01-03T20:00:00+00:00",
  online: false,
  approximate: true,
};
const SAM = {
  xuid: "sam",
  gamertag: "Sam",
  total_playtime_seconds: 1800,
  session_count: 1,
  first_seen: "2026-01-02T09:00:00+00:00",
  last_seen: "2026-01-02T09:30:00+00:00",
  online: true,
  approximate: false,
};

const ALEX_SESSIONS = {
  xuid: "alex",
  gamertag: "Alex",
  sessions: [
    {
      connected_at: "2026-01-03T19:00:00+00:00",
      spawned_at: "2026-01-03T19:00:06+00:00",
      disconnected_at: "2026-01-03T20:00:00+00:00",
      duration_seconds: 3600,
      end_reason: "reconstructed",
      in_progress: false,
      approximate: true,
    },
    {
      connected_at: "2026-01-01T08:00:00+00:00",
      spawned_at: "2026-01-01T08:00:05+00:00",
      disconnected_at: "2026-01-01T09:00:00+00:00",
      duration_seconds: 3600,
      end_reason: "observed",
      in_progress: false,
      approximate: false,
    },
  ],
};

/** A fetch stub with per-URL response queues (falls back to the last entry). */
function mockFetch(routes: Record<string, unknown[]>) {
  const calls: Record<string, number> = {};
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const queue = routes[key] ?? routes[url];
    if (!queue) return new Response("{}", { status: 200 });
    const n = calls[key] ?? 0;
    calls[key] = n + 1;
    const body = queue[Math.min(n, queue.length - 1)];
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("Players section", () => {
  it("7.1 is registered in the section list and appears in navigation", async () => {
    expect(sections.map((s) => s.path)).toContain("/players");
    expect(sections.find((s) => s.path === "/players")?.label).toBe("Players");

    mockFetch({ "GET /api/players": [{ players: [], recorded_since: null }] });
    const { App } = await import("../App");
    renderApp(<App />);
    expect(screen.getByRole("link", { name: "Players" })).toBeInTheDocument();
  });

  it("7.2 renders the roster sorted by last seen, online players distinguished", async () => {
    mockFetch({
      "GET /api/players": [{ players: [SAM, ALEX], recorded_since: ALEX.first_seen }],
    });
    renderApp(<Players />);

    const rows = await screen.findAllByRole("button", { pressed: false });
    // Alex was last seen on the 3rd, Sam on the 2nd → Alex first.
    expect(within(rows[0]).getByText("Alex")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Sam")).toBeInTheDocument();
    // Sam is online.
    expect(within(rows[1]).getByText("online")).toBeInTheDocument();
    expect(within(rows[0]).queryByText("online")).toBeNull();
  });

  it("7.3 presents an approximate total as approximate and an exact one plainly", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX, SAM], recorded_since: ALEX.first_seen }],
    });
    renderApp(<Players />);

    const rows = await screen.findAllByRole("button");
    // Alex's total is approximate (a reconstructed session); Sam's is not.
    expect(within(rows[0]).getByText("approx")).toBeInTheDocument();
    expect(within(rows[0]).getByText(/~2h/)).toBeInTheDocument();
    expect(within(rows[1]).queryByText("approx")).toBeNull();
  });

  it("7.3 marks a reconstructed session and leaves an observed one unmarked", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/players/alex/sessions": [ALEX_SESSIONS],
    });
    renderApp(<Players />);
    await userEvent.click(await screen.findByRole("button", { name: /Alex/ }));

    const history = await screen.findByTestId("session-history");
    const items = within(history).getAllByRole("listitem");
    expect(within(items[0]).getByText("approx")).toBeInTheDocument();
    expect(
      within(items[0]).getByText(/end time reconstructed after cobble restarted/),
    ).toBeInTheDocument();
    expect(within(items[1]).queryByText("approx")).toBeNull();
    expect(within(items[1]).getByText("left")).toBeInTheDocument();
  });

  it("7.4 shows a player's sessions most recent first on selection", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/players/alex/sessions": [ALEX_SESSIONS],
    });
    renderApp(<Players />);
    await userEvent.click(await screen.findByRole("button", { name: /Alex/ }));

    const history = await screen.findByTestId("session-history");
    const items = within(history).getAllByRole("listitem");
    const times = items.map((li) => within(li).getByText(/2026/).textContent ?? "");
    expect(new Date(times[0]).getTime()).toBeGreaterThan(new Date(times[1]).getTime());
  });

  it("7.5 updates the roster when the online set changes, with no reload", async () => {
    const fetchFn = mockFetch({
      "GET /api/players": [
        { players: [ALEX], recorded_since: ALEX.first_seen },
        { players: [ALEX, { ...SAM, online: true }], recorded_since: ALEX.first_seen },
      ],
    });
    renderApp(<Players />);
    await screen.findByText("Alex");
    expect(screen.queryByText("Sam")).toBeNull();

    // A connect arrives on the existing status stream.
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE_STATUS, online_players: [{ xuid: "sam", gamertag: "Sam" }] });

    expect(await screen.findByText("Sam")).toBeInTheDocument();
    const rosterCalls = fetchFn.mock.calls.filter((c) => c[0] === "/api/players");
    expect(rosterCalls.length).toBeGreaterThanOrEqual(2);
  });

  it("7.6 shows an empty-state explanation and the recorded-since date, not an error", async () => {
    mockFetch({
      "GET /api/players": [{ players: [], recorded_since: "2026-01-01T00:00:00+00:00" }],
    });
    renderApp(<Players />);

    expect(await screen.findByText("No player history yet.")).toBeInTheDocument();
    expect(screen.getByTestId("recorded-since")).toHaveTextContent(
      /History recorded since/,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
