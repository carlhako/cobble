import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Configuration } from "../sections/Configuration";
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
  update: null,
  backup: null,
  config: { pending: false, pending_count: 0 },
};

const SETTINGS = [
  {
    key: "difficulty",
    value: "easy",
    recognised: true,
    schema: {
      key: "difficulty",
      type: "enum",
      default: "easy",
      description: "World difficulty.",
      members: ["peaceful", "easy", "normal", "hard"],
      minimum: null,
      maximum: null,
    },
  },
  {
    key: "allow-cheats",
    value: "false",
    recognised: true,
    schema: {
      key: "allow-cheats",
      type: "bool",
      default: "false",
      description: "Allow cheat commands.",
      members: null,
      minimum: null,
      maximum: null,
    },
  },
  {
    key: "view-distance",
    value: "32",
    recognised: true,
    schema: {
      key: "view-distance",
      type: "int",
      default: "32",
      description: "Render distance in chunks.",
      members: null,
      minimum: 5,
      maximum: 96,
    },
  },
  {
    key: "player-position-acceptance-threshold",
    value: "0.5",
    recognised: true,
    schema: {
      key: "player-position-acceptance-threshold",
      type: "float",
      default: "0.5",
      description: "Position divergence tolerance.",
      members: null,
      minimum: 0,
      maximum: null,
    },
  },
  {
    key: "level-name",
    value: "Bedrock level",
    recognised: true,
    schema: {
      key: "level-name",
      type: "string",
      default: "Bedrock level",
      description: "World directory.",
      members: null,
      minimum: null,
      maximum: null,
    },
  },
  {
    key: "operator-added-key",
    value: "kept",
    recognised: false,
    schema: null,
  },
];

const WORLDS = {
  worlds: [
    { name: "Bedrock level", is_current: true },
    { name: "Creative Flats", is_current: false },
  ],
  current: "Bedrock level",
  current_present: true,
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

const READ_OK = { "GET /api/config/worlds": WORLDS };

afterEach(() => vi.unstubAllGlobals());

async function renderReady(routes: Record<string, unknown>, status: unknown = BASE) {
  mockFetch(routes);
  renderApp(<Configuration />);
  await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
  push(status);
  return screen;
}

describe("Configuration section", () => {
  it("7.1 is registered as a section without any shell change", () => {
    const s = sections.find((x) => x.path === "/configuration");
    expect(s?.label).toBe("Configuration");
  });

  it("7.2 renders a type-appropriate input, default + description, and marks unrecognised", async () => {
    await renderReady({
      ...READ_OK,
      "GET /api/config": { settings: SETTINGS, pending: [] },
    });

    // enum -> a <select> with the member options
    const difficulty = await screen.findByLabelText("difficulty");
    expect(difficulty.tagName).toBe("SELECT");
    expect(
      within(difficulty as HTMLElement).getByRole("option", { name: "hard" }),
    ).toBeInTheDocument();

    // bool -> a checkbox; int -> number; description + default visible
    expect((screen.getByLabelText("allow-cheats") as HTMLInputElement).type).toBe(
      "checkbox",
    );
    expect((screen.getByLabelText("view-distance") as HTMLInputElement).type).toBe(
      "number",
    );
    // float -> number input that accepts decimals
    const flt = screen.getByLabelText(
      "player-position-acceptance-threshold",
    ) as HTMLInputElement;
    expect(flt.type).toBe("number");
    expect(flt.step).toBe("any");
    expect(screen.getByText("World difficulty.")).toBeInTheDocument();
    expect(screen.getAllByText(/Default:/)[0]).toBeInTheDocument();

    // unrecognised -> editable text, marked
    const op = screen.getByLabelText(/operator-added-key/) as HTMLInputElement;
    expect(op.type).toBe("text");
    expect(op.value).toBe("kept");
    expect(screen.getByText("not recognised")).toBeInTheDocument();
  });

  it("7.3 a rejected save keeps entered values and shows the reason per setting", async () => {
    const fetchFn = mockFetch({
      ...READ_OK,
      "GET /api/config": { settings: SETTINGS, pending: [] },
      "POST /api/config": {
        ok: false,
        errors: [
          {
            key: "operator-added-key",
            severity: "error",
            message: "must be a whole number",
          },
        ],
        warnings: [],
        changed: [],
        notes: [],
        pending: [],
      },
    });
    renderApp(<Configuration />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);

    // Two edits the controls can hold; the server rejects the batch.
    await userEvent.selectOptions(await screen.findByLabelText("difficulty"), "normal");
    const op = screen.getByLabelText(/operator-added-key/);
    await userEvent.clear(op);
    await userEvent.type(op, "seventeen");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(fetchFn).toHaveBeenCalledWith(
        "/api/config",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(await screen.findByText("must be a whole number")).toBeInTheDocument();
    // entered values are retained, not reverted to the stored values
    expect((screen.getByLabelText("difficulty") as HTMLSelectElement).value).toBe(
      "normal",
    );
    expect((screen.getByLabelText(/operator-added-key/) as HTMLInputElement).value).toBe(
      "seventeen",
    );
  });

  it("7.3 an accepted save with a warning shows the warning alongside the setting", async () => {
    mockFetch({
      ...READ_OK,
      "GET /api/config": { settings: SETTINGS, pending: [] },
      "POST /api/config": {
        ok: true,
        errors: [],
        warnings: [
          {
            key: "view-distance",
            severity: "warning",
            message: "outside the recommended range 5 to 96",
          },
        ],
        changed: ["view-distance"],
        notes: [],
        pending: [],
      },
    });
    renderApp(<Configuration />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);

    const vd = await screen.findByLabelText("view-distance");
    await userEvent.clear(vd);
    await userEvent.type(vd, "500");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText(/outside the recommended range/)).toBeInTheDocument();
  });

  it("7.4 presents level-name as a world picker; creating a new world is explicit and confirmed", async () => {
    const fetchFn = mockFetch({
      ...READ_OK,
      "GET /api/config": { settings: SETTINGS, pending: [] },
      "POST /api/config": {
        ok: true,
        errors: [],
        warnings: [],
        changed: ["level-name"],
        notes: [
          "No world named 'Skyblock' exists yet; a new, empty world will be created when the server next starts. The existing worlds are kept.",
        ],
        pending: [],
      },
    });
    renderApp(<Configuration />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(BASE);

    const picker = await screen.findByLabelText("level-name");
    expect(picker.tagName).toBe("SELECT");
    expect(
      within(picker as HTMLElement).getByRole("option", { name: "Creative Flats" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /create a new world/i }));
    const dialog = await screen.findByRole("alertdialog", { name: "create a new world" });
    expect(within(dialog).getByText(/existing worlds are kept/i)).toBeInTheDocument();

    // no write until the explicit confirm
    expect(fetchFn).not.toHaveBeenCalledWith(
      "/api/config",
      expect.objectContaining({ method: "POST" }),
    );

    await userEvent.type(within(dialog).getByLabelText("new world name"), "Skyblock");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Create and save" }),
    );
    await waitFor(() =>
      expect(fetchFn).toHaveBeenCalledWith(
        "/api/config",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(
      await screen.findByText(/new, empty world will be created/i),
    ).toBeInTheDocument();
  });

  it("7.4 shows the current level value as missing when no such world exists", async () => {
    await renderReady({
      "GET /api/config/worlds": {
        worlds: [{ name: "Creative Flats", is_current: false }],
        current: "Ghost World",
        current_present: false,
      },
      "GET /api/config": {
        settings: SETTINGS.map((s) =>
          s.key === "level-name" ? { ...s, value: "Ghost World" } : s,
        ),
        pending: [],
      },
    });
    expect(
      await screen.findByText(/No world named .Ghost World. exists/),
    ).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("level-name") as HTMLElement).getByRole("option", {
        name: /Ghost World \(missing\)/,
      }),
    ).toBeInTheDocument();
  });

  it("7.5 offers a restart for pending changes, states deferred timing, and can defer", async () => {
    const fetchFn = mockFetch({
      "GET /api/config/worlds": WORLDS,
      "GET /api/config": {
        settings: SETTINGS,
        pending: [{ key: "difficulty", saved: "hard", in_effect: "easy" }],
      },
      "POST /api/server/restart": BASE,
    });
    renderApp(<Configuration />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE, config: { pending: true, pending_count: 1 } });

    const panel = await screen.findByLabelText("pending configuration changes");
    expect(
      within(panel).getByText(
        /take effect the next time the server starts for any reason/i,
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByText("hard")).toBeInTheDocument();
    expect(within(panel).getByText("easy")).toBeInTheDocument();

    await userEvent.click(within(panel).getByRole("button", { name: "Later" }));
    expect(within(panel).getByText(/Deferred\./)).toBeInTheDocument();
    expect(fetchFn).not.toHaveBeenCalledWith("/api/server/restart", expect.anything());
  });

  it("7.5 accepting the restart calls restart", async () => {
    const fetchFn = mockFetch({
      "GET /api/config/worlds": WORLDS,
      "GET /api/config": {
        settings: SETTINGS,
        pending: [{ key: "difficulty", saved: "hard", in_effect: "easy" }],
      },
      "POST /api/server/restart": BASE,
    });
    renderApp(<Configuration />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE, config: { pending: true, pending_count: 1 } });

    const panel = await screen.findByLabelText("pending configuration changes");
    await userEvent.click(
      within(panel).getByRole("button", { name: "Restart now to apply" }),
    );
    await waitFor(() =>
      expect(fetchFn).toHaveBeenCalledWith(
        "/api/server/restart",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("7.5 offers no restart when the server is stopped and nothing is pending", async () => {
    await renderReady(
      {
        "GET /api/config/worlds": WORLDS,
        "GET /api/config": { settings: SETTINGS, pending: [] },
      },
      { ...BASE, run_state: "stopped", config: { pending: false, pending_count: 0 } },
    );
    await screen.findByLabelText("difficulty");
    expect(
      screen.queryByLabelText("pending configuration changes"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /restart now/i }),
    ).not.toBeInTheDocument();
  });

  it("7.6 shows an already-pending state on open, with saved and in-effect values", async () => {
    await renderReady(
      {
        "GET /api/config/worlds": WORLDS,
        "GET /api/config": {
          settings: SETTINGS,
          pending: [
            { key: "difficulty", saved: "hard", in_effect: "easy" },
            { key: "max-players", saved: "20", in_effect: "10" },
          ],
        },
      },
      { ...BASE, config: { pending: true, pending_count: 2 } },
    );
    const panel = await screen.findByLabelText("pending configuration changes");
    expect(within(panel).getByText("difficulty")).toBeInTheDocument();
    expect(within(panel).getByText("max-players")).toBeInTheDocument();
    expect(within(panel).getByText("20")).toBeInTheDocument();
    expect(within(panel).getByText("10")).toBeInTheDocument();
  });

  it("7.7 disables saving during maintenance, names the operation, and re-enables when it ends", async () => {
    await renderReady(
      {
        "GET /api/config/worlds": WORLDS,
        "GET /api/config": { settings: SETTINGS, pending: [] },
      },
      { ...BASE, maintenance: { operation: "updating", step: "activating" } },
    );

    // settings still visible
    expect(await screen.findByLabelText("difficulty")).toBeInTheDocument();
    expect(screen.getByText(/an update is in progress/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();

    // maintenance ends -> saving available again without a manual refresh
    push({ ...BASE, maintenance: null });
    await waitFor(() =>
      expect(screen.queryByText(/an update is in progress/i)).not.toBeInTheDocument(),
    );
  });
});
