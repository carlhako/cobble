import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sections } from "../sections";
import { Gamerules } from "../sections/Gamerules";
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
  update: null,
  backup: null,
  config: { pending: false, pending_count: 0 },
  gamerules: {
    active_world: "world-a",
    liveness: "live",
    last_read_at: "2026-04-01T09:00:00+00:00",
    report: null,
  },
};

const RULES = [
  {
    name: "mobGriefing",
    raw: "true",
    value: true,
    type: "bool",
    recognised: true,
    description: "Mobs can change blocks.",
  },
  {
    name: "randomTickSpeed",
    raw: "1",
    value: 1,
    type: "int",
    recognised: true,
    minimum: 0,
    maximum: 4096,
    description: "Random block ticks per chunk.",
  },
  {
    name: "playerWaypoints",
    raw: "everyone",
    value: "everyone",
    type: "enum",
    recognised: true,
    members: ["everyone", "disabled"],
    description: "Locator bar waypoints.",
  },
  {
    name: "futureRule",
    raw: "wobble",
    value: "wobble",
    type: null,
    recognised: false,
  },
];

const LIVE_VIEW = {
  level_name: "world-a",
  liveness: "live",
  sampled_at: null,
  rules: RULES,
  report: null,
};

const DEFAULTS_EMPTY = {
  defaults: {},
  catalogue: [
    {
      name: "keepInventory",
      type: "bool",
      default: false,
      description: "Keep inventory on death.",
      minimum: null,
      maximum: null,
      members: [],
    },
    {
      name: "randomTickSpeed",
      type: "int",
      default: 1,
      description: "Random ticks.",
      minimum: 0,
      maximum: 4096,
      members: [],
    },
  ],
};

function mockFetch(routes: Record<string, unknown>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const entry = routes[key] ?? routes[url];
    const status =
      typeof entry === "object" && entry && "__status" in entry
        ? (entry as { __status: number }).__status
        : 200;
    const body =
      typeof entry === "object" && entry && "__body" in entry
        ? (entry as { __body: unknown }).__body
        : (entry ?? {});
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

async function renderReady(routes: Record<string, unknown>, status: unknown = BASE) {
  mockFetch({ "GET /api/gamerules/defaults": DEFAULTS_EMPTY, ...routes });
  renderApp(<Gamerules />);
  await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
  push(status);
  return screen;
}

describe("Gamerules section", () => {
  it("6.1 is registered as a section", () => {
    const s = sections.find((x) => x.path === "/gamerules");
    expect(s?.label).toBe("Gamerules");
  });

  it("6.1 renders one control of each kind from a fixture set", async () => {
    await renderReady({ "GET /api/gamerules": LIVE_VIEW });

    expect(((await screen.findByLabelText(/mobGriefing/)) as HTMLInputElement).type).toBe(
      "checkbox",
    );
    expect((screen.getByLabelText(/randomTickSpeed/) as HTMLInputElement).type).toBe(
      "number",
    );
    const wp = screen.getByLabelText(/playerWaypoints/);
    expect(wp.tagName).toBe("SELECT");
    expect(
      within(wp as HTMLElement).getByRole("option", { name: "disabled" }),
    ).toBeInTheDocument();
    const unk = screen.getByLabelText(/futureRule/) as HTMLInputElement;
    expect(unk.type).toBe("text");
    expect(screen.getByText("unrecognised")).toBeInTheDocument();
  });

  it("6.2 applies immediately and shows the value the server read back, no restart prompt", async () => {
    // operator unchecks mobGriefing, but the server reports it still true
    mockFetch({
      "GET /api/gamerules/defaults": DEFAULTS_EMPTY,
      "GET /api/gamerules": LIVE_VIEW,
      "POST /api/gamerules": {
        queued: false,
        level_name: "world-a",
        rule: { ...RULES[0], value: true },
        rules: RULES,
      },
    });
    renderApp(<Gamerules />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);

    const cb = (await screen.findByLabelText(/mobGriefing/)) as HTMLInputElement;
    await userEvent.click(cb);
    await waitFor(() =>
      expect((screen.getByLabelText(/mobGriefing/) as HTMLInputElement).checked).toBe(
        true,
      ),
    );
    expect(screen.queryByRole("button", { name: /restart/i })).not.toBeInTheDocument();
  });

  it("6.3 shows a refusal against its rule and reverts the displayed value", async () => {
    mockFetch({
      "GET /api/gamerules/defaults": DEFAULTS_EMPTY,
      "GET /api/gamerules": LIVE_VIEW,
      "POST /api/gamerules": {
        __status: 409,
        __body: {
          detail: {
            error: "gamerule_refused",
            rule: "randomTickSpeed",
            detail: "randomTickSpeed must be between 0 and 4096",
          },
        },
      },
    });
    renderApp(<Gamerules />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);

    const num = (await screen.findByLabelText(/randomTickSpeed/)) as HTMLInputElement;
    await userEvent.clear(num);
    await userEvent.type(num, "99999");
    act(() => num.blur());

    expect(await screen.findByText(/must be between 0 and 4096/)).toBeInTheDocument();
    await waitFor(() =>
      expect((screen.getByLabelText(/randomTickSpeed/) as HTMLInputElement).value).toBe(
        "1",
      ),
    );
  });

  it("6.4 marks a stopped world's values as recorded with the time taken", async () => {
    await renderReady(
      {
        "GET /api/gamerules": {
          level_name: "world-a",
          liveness: "recorded",
          sampled_at: "2026-04-01T09:00:00+00:00",
          rules: RULES,
          report: null,
        },
      },
      { ...BASE, run_state: "stopped" },
    );
    expect(await screen.findByText(/values recorded for/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/mobGriefing/)).toBeInTheDocument(); // values still shown
  });

  it("6.4 an unread world says so rather than showing values", async () => {
    await renderReady(
      {
        "GET /api/gamerules": {
          level_name: "fresh-world",
          liveness: "unread",
          sampled_at: null,
          rules: [],
          report: null,
        },
      },
      { ...BASE, run_state: "stopped" },
    );
    expect(await screen.findByText(/have not been read/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/mobGriefing/)).not.toBeInTheDocument();
  });

  it("6.5 states that a change made while stopped applies at the next start", async () => {
    mockFetch({
      "GET /api/gamerules/defaults": DEFAULTS_EMPTY,
      "GET /api/gamerules": {
        level_name: "world-a",
        liveness: "recorded",
        sampled_at: "2026-04-01T09:00:00+00:00",
        rules: RULES,
        report: null,
      },
      "POST /api/gamerules": {
        queued: true,
        level_name: "world-a",
        pending: { mobGriefing: false },
      },
    });
    renderApp(<Gamerules />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE, run_state: "stopped" });

    await userEvent.click(await screen.findByLabelText(/mobGriefing/));
    expect(
      await screen.findByText(/will be applied when the server next starts/i),
    ).toBeInTheDocument();
  });

  it("6.6 surfaces a report with its rules and an acknowledge control that dismisses it", async () => {
    const fetchFn = mockFetch({
      "GET /api/gamerules/defaults": DEFAULTS_EMPTY,
      "GET /api/gamerules": {
        ...LIVE_VIEW,
        report: {
          level_name: "world-a",
          kind: "adoption",
          created_at: "2026-04-01T09:00:00+00:00",
          rules: { mobGriefing: false },
        },
      },
      "POST /api/gamerules/acknowledge": { ok: true },
    });
    renderApp(<Gamerules />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);

    const panel = await screen.findByLabelText("gamerule report");
    expect(within(panel).getByText(/changed outside cobble/i)).toBeInTheDocument();
    expect(within(panel).getByText("mobGriefing")).toBeInTheDocument();

    // after acknowledging, the reload returns a view with no report
    expect(fetchFn).toHaveBeenCalled();
    mockFetch({
      "GET /api/gamerules/defaults": DEFAULTS_EMPTY,
      "GET /api/gamerules": LIVE_VIEW,
      "POST /api/gamerules/acknowledge": { ok: true },
    });
    await userEvent.click(within(panel).getByRole("button", { name: "Acknowledge" }));
    await waitFor(() =>
      expect(screen.queryByLabelText("gamerule report")).not.toBeInTheDocument(),
    );
  });

  it("6.7 shows the preferred-defaults editor separately, stating it applies to unseen worlds", async () => {
    await renderReady({ "GET /api/gamerules": LIVE_VIEW });
    const editor = await screen.findByLabelText("preferred gamerule defaults");
    expect(
      within(editor).getByText(/world cobble has not seen before/i),
    ).toBeInTheDocument();
    // distinct from the active world's panel
    expect(editor).not.toContainElement(screen.getByLabelText(/mobGriefing/));
  });

  it("6.8 disables editing during maintenance, keeps values visible, re-enables when it ends", async () => {
    await renderReady(
      { "GET /api/gamerules": LIVE_VIEW },
      {
        ...BASE,
        maintenance: { operation: "backing_up", step: "capturing" },
      },
    );

    expect(await screen.findByLabelText(/mobGriefing/)).toBeDisabled();
    expect(screen.getByText(/a backup is in progress/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/mobGriefing/)).toBeInTheDocument(); // still visible

    push({ ...BASE, maintenance: null });
    await waitFor(() => expect(screen.getByLabelText(/mobGriefing/)).not.toBeDisabled());
  });
});
