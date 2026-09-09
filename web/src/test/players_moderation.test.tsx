import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Players } from "../sections/Players";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

const BASE_STATUS = {
  run_state: "running",
  version: "1.0.0.1",
  uptime_seconds: 10,
  online_players: [{ xuid: "alex", gamertag: "Alex" }],
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
  gamerules: null,
  access: {
    running: true,
    in_effect: "on",
    saved: true,
    disagreement: false,
    ban_count: 0,
  },
};

const ALEX = {
  xuid: "alex",
  gamertag: "Alex",
  total_playtime_seconds: 7200,
  session_count: 3,
  first_seen: "2026-01-01T08:00:00+00:00",
  last_seen: "2026-01-03T20:00:00+00:00",
  online: true,
  approximate: false,
};
const SAM = {
  ...ALEX,
  xuid: "sam",
  gamertag: "Sam",
  online: false,
  last_seen: "2026-01-02T09:30:00+00:00",
};

const SESSIONS = { xuid: "alex", gamertag: "Alex", sessions: [] };

function access(over: Partial<Record<string, unknown>> = {}) {
  return {
    allowlist: {
      readable: true,
      entries: [
        { name: "Alex", xuid: "alex", has_identifier: true, has_played: true },
        { name: "GhostFriend", xuid: null, has_identifier: false, has_played: false },
      ],
    },
    permissions: [
      { xuid: "alex", level: "operator", name: "Alex" },
      { xuid: "x-unknown", level: "operator", name: null },
    ],
    enforcement: { saved: true, in_effect: "on", running: true, disagreement: false },
    bans: [],
    ...over,
  };
}

interface Entry {
  status?: number;
  body: unknown;
}

function mockFetch(routes: Record<string, (Entry | unknown)[]>) {
  const calls: Record<string, number> = {};
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const queue = routes[key] ?? routes[url];
    if (!queue) return new Response("{}", { status: 200 });
    const n = calls[key] ?? 0;
    calls[key] = n + 1;
    const raw = queue[Math.min(n, queue.length - 1)];
    const entry: Entry =
      raw && typeof raw === "object" && "body" in (raw as object)
        ? (raw as Entry)
        : { body: raw };
    return new Response(JSON.stringify(entry.body), {
      status: entry.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function pushStatus(data: unknown) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() => es.emit(data));
}

afterEach(() => vi.unstubAllGlobals());

async function primeStatus(over: Record<string, unknown> = {}) {
  await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
  pushStatus({ ...BASE_STATUS, ...over });
}

async function openAlex() {
  await userEvent.click(await screen.findByRole("button", { name: /Alex/ }));
  return screen.findByTestId("player-access");
}

describe("Players moderation (M6, section 9)", () => {
  it("9.1 offers kick/ban/permission actions; kick unavailable offline or server stopped", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX, SAM], recorded_since: ALEX.first_seen }],
      "GET /api/access": [access()],
      "GET /api/players/alex/sessions": [SESSIONS],
      "GET /api/players/sam/sessions": [{ ...SESSIONS, xuid: "sam", gamertag: "Sam" }],
    });
    renderApp(<Players />);
    await primeStatus();

    // Alex is online -> kick enabled
    let panel = await openAlex();
    expect(within(panel).getByRole("button", { name: "Kick" })).toBeEnabled();
    expect(within(panel).getByRole("button", { name: "Ban" })).toBeEnabled();
    expect(within(panel).getByLabelText("permission level")).toBeInTheDocument();

    // Sam is offline -> kick disabled, durable actions available
    await userEvent.click(await screen.findByRole("button", { name: /Sam/ }));
    panel = await screen.findByTestId("player-access");
    expect(within(panel).getByRole("button", { name: "Kick" })).toBeDisabled();
    expect(within(panel).getByRole("button", { name: "Ban" })).toBeEnabled();
  });

  it("9.1 kick is unavailable while the server is not running", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/access": [access()],
      "GET /api/players/alex/sessions": [SESSIONS],
    });
    renderApp(<Players />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    pushStatus({ ...BASE_STATUS, run_state: "stopped" });

    const panel = await openAlex();
    expect(within(panel).getByRole("button", { name: "Kick" })).toBeDisabled();
  });

  it("9.2 shows a banned player's reason and time; an unbanned absent player does not read as banned", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX, SAM], recorded_since: ALEX.first_seen }],
      "GET /api/access": [
        access({
          allowlist: { readable: true, entries: [] },
          bans: [
            {
              xuid: "alex",
              name: "Alex",
              reason: "griefing spawn",
              banned_at: "2026-02-01T12:00:00+00:00",
              lifted_at: null,
              active: true,
            },
          ],
        }),
      ],
      "GET /api/players/alex/sessions": [SESSIONS],
      "GET /api/players/sam/sessions": [{ ...SESSIONS, xuid: "sam", gamertag: "Sam" }],
    });
    renderApp(<Players />);

    let panel = await openAlex();
    const detail = within(panel).getByTestId("ban-detail");
    expect(detail).toHaveTextContent("griefing spawn");
    expect(detail).toHaveTextContent("2026");

    // Sam: not banned, not on the allowlist -> must not read as banned
    await userEvent.click(await screen.findByRole("button", { name: /Sam/ }));
    panel = await screen.findByTestId("player-access");
    expect(within(panel).queryByTestId("ban-detail")).toBeNull();
    expect(within(panel).queryByText("banned")).toBeNull();
  });

  it("9.3 ban confirmation names who else enforcement would exclude; nothing is submitted until confirmed", async () => {
    const fetchFn = mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/access": [
        access({
          enforcement: {
            saved: false,
            in_effect: "off",
            running: true,
            disagreement: false,
          },
        }),
      ],
      "GET /api/players/alex/sessions": [SESSIONS],
      "POST /api/players/alex/ban": [
        {
          status: 409,
          body: {
            detail: {
              error: "confirmation_required",
              detail: "enabling allowlist enforcement would exclude other players",
              would_exclude: ["Kid", "Mum"],
            },
          },
        },
        {
          body: {
            xuid: "alex",
            name: "Alex",
            needs_confirmation: false,
            would_exclude: [],
            steps: ["recorded", "enforcement_enabled"],
            kick: null,
            identifier_written: true,
          },
        },
      ],
    });
    renderApp(<Players />);
    const panel = await openAlex();
    await userEvent.click(within(panel).getByRole("button", { name: "Ban" }));

    const dialog = await screen.findByTestId("ban-confirm");
    expect(within(dialog).getByText("Kid")).toBeInTheDocument();
    expect(within(dialog).getByText("Mum")).toBeInTheDocument();
    // first ban call was the (rejected) preview; nothing else submitted yet
    const banCalls = () =>
      fetchFn.mock.calls.filter((c) => c[0] === "/api/players/alex/ban").length;
    expect(banCalls()).toBe(1);

    await userEvent.click(
      within(dialog).getByRole("button", { name: /add the players above/i }),
    );
    await waitFor(() => expect(banCalls()).toBe(2));
    // the confirmed call carries confirm + permit_excluded
    const banRequests = fetchFn.mock.calls.filter(
      (c) => c[0] === "/api/players/alex/ban",
    );
    const confirmedInit = banRequests[1]?.[1] as RequestInit | undefined;
    const confirmedBody = JSON.parse((confirmedInit?.body as string) ?? "{}");
    expect(confirmedBody).toMatchObject({ confirm: true, permit_excluded: true });
  });

  it("9.4 shows allowlist and permission records, including no-roster and no-name entries", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/access": [access()],
    });
    renderApp(<Players />);

    const view = await screen.findByTestId("allowlist-view");
    expect(within(view).getByText("GhostFriend")).toBeInTheDocument();
    expect(within(view).getByText(/never played here/)).toBeInTheDocument();
    expect(within(view).getByText("identified by name only")).toBeInTheDocument();
    const perms = within(view).getByTestId("permissions-view");
    expect(within(perms).getByText("(name unknown)")).toBeInTheDocument();
    expect(within(perms).getByText("x-unknown")).toBeInTheDocument();
  });

  it("9.5 presents live enforcement separately from the saved setting, including disagreement and unknown", async () => {
    // disagreement
    mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/access": [
        access({
          enforcement: {
            saved: false,
            in_effect: "on",
            running: true,
            disagreement: true,
          },
        }),
      ],
    });
    const { unmount } = renderApp(<Players />);
    const disagree = await screen.findByTestId("enforcement");
    expect(disagree).toHaveTextContent(/disagree/i);
    expect(disagree).toHaveTextContent(/in effect now/i);
    unmount();
    vi.unstubAllGlobals();

    // unknown
    mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/access": [
        access({
          enforcement: {
            saved: true,
            in_effect: "unknown",
            running: true,
            disagreement: false,
          },
        }),
      ],
    });
    renderApp(<Players />);
    expect(await screen.findByTestId("enforcement")).toHaveTextContent(/unknown/i);
  });

  it("9.6 moderation is unavailable during maintenance and restored when it ends, no reload", async () => {
    mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/access": [access()],
      "GET /api/players/alex/sessions": [SESSIONS],
    });
    renderApp(<Players />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    pushStatus({ ...BASE_STATUS, maintenance: { operation: "backing_up", step: null } });

    let panel = await openAlex();
    expect(within(panel).getByTestId("moderation-unavailable")).toHaveTextContent(
      /backing_up/,
    );
    expect(within(panel).getByRole("button", { name: "Ban" })).toBeDisabled();

    pushStatus({ ...BASE_STATUS, maintenance: null });
    panel = await screen.findByTestId("player-access");
    expect(within(panel).queryByTestId("moderation-unavailable")).toBeNull();
    expect(within(panel).getByRole("button", { name: "Ban" })).toBeEnabled();
  });

  it("9.7 reflects a completed action without a reload and shows a refusal against the player", async () => {
    const fetchFn = mockFetch({
      "GET /api/players": [{ players: [ALEX], recorded_since: ALEX.first_seen }],
      "GET /api/access": [
        access(),
        access(),
        access({
          bans: [
            {
              xuid: "alex",
              name: "Alex",
              reason: "",
              banned_at: "2026-02-02T00:00:00+00:00",
              lifted_at: null,
              active: true,
            },
          ],
        }),
      ],
      "GET /api/players/alex/sessions": [SESSIONS],
      "POST /api/players/alex/kick": [
        {
          status: 409,
          body: {
            detail: { error: "player_not_connected", detail: "Alex is not connected" },
          },
        },
      ],
      "POST /api/players/alex/ban": [
        {
          body: {
            xuid: "alex",
            name: "Alex",
            needs_confirmation: false,
            would_exclude: [],
            steps: ["recorded", "allowlist_updated"],
            kick: null,
            identifier_written: true,
          },
        },
      ],
    });
    renderApp(<Players />);
    await primeStatus();
    const panel = await openAlex();

    // refusal is shown against the player it concerns
    await userEvent.click(within(panel).getByRole("button", { name: "Kick" }));
    const err = await screen.findByTestId("player-action-error");
    expect(err).toHaveTextContent("Alex");
    expect(err).toHaveTextContent(/not connected/);

    // a completed ban refetches access (no operator reload) and the panel flips to Unban
    const accessCalls = () =>
      fetchFn.mock.calls.filter((c) => c[0] === "/api/access").length;
    const before = accessCalls();
    await userEvent.click(within(panel).getByRole("button", { name: "Ban" }));
    await waitFor(() => expect(accessCalls()).toBeGreaterThan(before));
    expect(
      await within(await screen.findByTestId("player-access")).findByRole("button", {
        name: "Unban",
      }),
    ).toBeInTheDocument();
  });
});
