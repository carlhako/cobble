import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NetworkLayout, NetworkView, ValidationIssue } from "../api/client";
import { Configuration } from "../sections/Configuration";
import { Network } from "../sections/Network";
import { sections } from "../sections";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

function push(data: unknown) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() => es.emit(data));
}

const BASE = {
  run_state: "stopped",
  version: "1.26.51.1",
  uptime_seconds: 0,
  online_players: [],
  players_incomplete: false,
  last_shutdown: null,
  bootstrap: "done",
  bootstrap_detail: "",
  last_crash: null,
  maintenance: null,
  version_info: { installed: "1.26.51.1", available: null, up_to_date: null },
  update: null,
  backup: null,
  config: { pending: false, pending_count: 0 },
};

const TRANSPORT = {
  value: "nethernet",
  saved: "nethernet",
  recommended: "nethernet",
  is_recommended: true,
  running: false,
  pending_restart: false,
};

const RAKNET: NetworkLayout = {
  settings: [
    {
      key: "server-port",
      value: "19132",
      present: true,
      protocol: "udp",
      label: "IPv4 port",
    },
    {
      key: "server-portv6",
      value: "19133",
      present: true,
      protocol: "udp",
      label: "IPv6 port",
    },
  ],
  udp_range: null,
  lan_discovery: null,
  forward: [
    { protocol: "udp", ports: "19132" },
    { protocol: "udp", ports: "19133", note: "Only needed for IPv6 players." },
  ],
  pin_required: false,
};

function nethernet(udp: NetworkLayout["udp_range"], udpValue: string): NetworkLayout {
  const forward: NetworkLayout["forward"] = [{ protocol: "tcp", ports: "19132" }];
  if (udp?.form === "range") forward.push({ protocol: "udp", ports: udpValue });
  if (udp?.form === "custom") forward.push({ protocol: "udp", ports: "19132-19232" });
  return {
    settings: [
      {
        key: "server-port",
        value: "19132",
        present: true,
        protocol: "tcp",
        label: "Handshake port",
      },
      {
        key: "server-ip",
        value: "",
        present: false,
        protocol: null,
        label: "Bind address",
      },
      {
        key: "server-udp-ports",
        value: udpValue,
        present: udpValue !== "",
        protocol: "udp",
        label: "Player UDP ports",
      },
    ],
    udp_range: udp,
    lan_discovery: { protocol: "udp", port: 7551 },
    forward,
    pin_required: udp?.form === "os",
  };
}

function view(
  layout: "nethernet" | "raknet",
  nn: NetworkLayout,
  conflicts: ValidationIssue[] = [],
): NetworkView {
  return {
    transport: { ...TRANSPORT, saved: layout },
    layout,
    layouts: { nethernet: nn, raknet: RAKNET },
    conflicts,
  };
}

const RANGE = nethernet(
  { form: "range", start: 19140, end: 19159, size: 20 },
  "19140-19159",
);
const OS = nethernet({ form: "os" }, "");
const CUSTOM_VALUE = "203.0.113.10:19132-19232:32000-32100";
const CUSTOM = nethernet(
  {
    form: "custom",
    value: CUSTOM_VALUE,
    local: [{ start: 32000, end: 32100 }],
    size: 101,
  },
  CUSTOM_VALUE,
);

const CONFLICT: ValidationIssue = {
  key: "server-udp-ports",
  severity: "warning",
  message: "server-udp-ports allows 5 UDP ports but max-players is 10.",
};

interface State {
  network: NetworkView;
  pending: { key: string; saved: string | null; in_effect: string | null }[];
  conflicts: ValidationIssue[];
  /** Applied on POST /api/config; returns the write response. */
  onWrite: (changes: Record<string, string>) => Record<string, unknown>;
}

const ACCEPTED = {
  ok: true,
  errors: [],
  warnings: [],
  changed: [],
  notes: [],
  pending: [],
};

function mockApi(state: State) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    let body: unknown = {};
    if (url === "/api/config/network") body = state.network;
    else if (url === "/api/config/worlds")
      body = { worlds: [], current: "Bedrock level", current_present: false };
    else if (url === "/api/config" && method === "GET")
      body = { settings: [], pending: state.pending, conflicts: state.conflicts };
    else if (url === "/api/config" && method === "POST")
      body = state.onWrite(JSON.parse(init!.body as string).changes);
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

function posted(fn: ReturnType<typeof vi.fn>): Record<string, string>[] {
  return fn.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")
    .map(([, init]) => JSON.parse((init as RequestInit).body as string).changes);
}

async function open(state: State, status: unknown = BASE) {
  const fn = mockApi(state);
  renderApp(<Network />);
  await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
  push(status);
  await screen.findByLabelText("Transport");
  return fn;
}

function state(network: NetworkView, onWrite?: State["onWrite"]): State {
  return { network, pending: [], conflicts: [], onWrite: onWrite ?? (() => ACCEPTED) };
}

function forwarded(): string[] {
  const region = screen.getByRole("region", { name: "ports to forward" });
  return within(region)
    .getAllByRole("listitem")
    .map((li) => li.textContent ?? "");
}

afterEach(() => vi.unstubAllGlobals());

describe("Network section", () => {
  it("6.1 is listed in navigation", () => {
    const s = sections.find((x) => x.path === "/network");
    expect(s?.label).toBe("Network");
    expect(s?.nav).not.toBe(false);
  });

  it("6.1 shows the NetherNet layout with protocols, LAN discovery and the ports to forward", async () => {
    await open(state(view("nethernet", RANGE)));

    const handshake = document.querySelector(
      'label[for="net-server-port"]',
    ) as HTMLElement;
    expect(handshake).toHaveTextContent("Handshake port");
    expect(within(handshake).getByText("TCP")).toBeInTheDocument();
    expect(screen.getByLabelText(/Bind address/)).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /Player UDP ports/ })).toBeInTheDocument();
    expect((screen.getByLabelText("From port") as HTMLInputElement).value).toBe("19140");
    expect((screen.getByLabelText("To port") as HTMLInputElement).value).toBe("19159");
    expect(screen.getByText("20 ports")).toBeInTheDocument();
    expect(screen.queryByLabelText(/IPv6 port/)).not.toBeInTheDocument();

    expect(screen.getByText("LAN discovery")).toBeInTheDocument();
    expect(screen.getByText("UDP 7551")).toBeInTheDocument();

    expect(
      screen.getByRole("heading", {
        name: "Forward on your router to this server's LAN address",
      }),
    ).toBeInTheDocument();
    expect(forwarded()).toEqual(["TCP 19132", "UDP 19140-19159"]);
  });

  it("6.1 shows the RakNet layout", async () => {
    await open(state(view("raknet", RANGE)));

    const v4 = document.querySelector('label[for="net-server-port"]') as HTMLElement;
    expect(v4).toHaveTextContent("IPv4 port");
    expect(within(v4).getByText("UDP")).toBeInTheDocument();
    expect(screen.getByLabelText(/IPv6 port/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Bind address/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: /Player UDP ports/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("LAN discovery")).not.toBeInTheDocument();
    expect(forwarded()).toEqual([
      "UDP 19132",
      "UDP 19133 · Only needed for IPv6 players.",
    ]);
  });

  it("6.1 has no public address field", async () => {
    await open(state(view("nethernet", RANGE)));
    expect(screen.queryByLabelText(/public/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/public (ip|address)/i)).not.toBeInTheDocument();
  });

  it("6.1 with the OS picking ports, says to pin a range instead of forwarding UDP", async () => {
    await open(state(view("nethernet", OS)));
    expect(forwarded()).toEqual(["TCP 19132"]);
    expect(screen.getByText(/can't connect yet/)).toBeInTheDocument();
    expect(screen.queryByLabelText("From port")).not.toBeInTheDocument();
  });

  it("6.2 pinning a range saves it as start-end", async () => {
    const s = state(view("nethernet", OS), () => {
      s.network = view("nethernet", RANGE);
      return ACCEPTED;
    });
    const fn = await open(s);

    await userEvent.click(screen.getByRole("radio", { name: "Pin a range" }));
    await userEvent.type(screen.getByLabelText("From port"), "19140");
    await userEvent.type(screen.getByLabelText("To port"), "19159");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(posted(fn)).toEqual([{ "server-udp-ports": "19140-19159" }]),
    );
    await waitFor(() => expect(forwarded()).toContain("UDP 19140-19159"));
  });

  it("6.2 equal from and to ports save as a single port", async () => {
    const fn = await open(state(view("nethernet", OS)));
    await userEvent.click(screen.getByRole("radio", { name: "Pin a range" }));
    await userEvent.type(screen.getByLabelText("From port"), "19140");
    await userEvent.type(screen.getByLabelText("To port"), "19140");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posted(fn)).toEqual([{ "server-udp-ports": "19140" }]));
  });

  it("6.2 letting the OS pick saves an empty value and then asks for a pin", async () => {
    const s = state(view("nethernet", RANGE), () => {
      s.network = view("nethernet", OS);
      return ACCEPTED;
    });
    const fn = await open(s);

    await userEvent.click(screen.getByRole("radio", { name: "Let the OS pick" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(posted(fn)).toEqual([{ "server-udp-ports": "" }]));
    expect(await screen.findByText(/can't connect yet/)).toBeInTheDocument();
  });

  it("6.2 switching the transport re-renders the layout and submits only the transport", async () => {
    const fn = await open(state(view("nethernet", RANGE)));

    await userEvent.selectOptions(screen.getByLabelText("Transport"), "raknet");
    expect(screen.getByLabelText(/IPv6 port/)).toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: /Player UDP ports/ }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posted(fn)).toEqual([{ transport: "raknet" }]));
  });

  it("6.2 a custom range is read-only, links to Configuration, and is never submitted", async () => {
    const fn = await open(state(view("nethernet", CUSTOM)));

    expect(screen.getByLabelText("player UDP ports value")).toHaveTextContent(
      CUSTOM_VALUE,
    );
    expect(screen.getByRole("link", { name: "Configuration" })).toHaveAttribute(
      "href",
      "/configuration",
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();

    const port = screen.getByLabelText(/Handshake port/);
    await userEvent.clear(port);
    await userEvent.type(port, "19200");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posted(fn)).toEqual([{ "server-port": "19200" }]));
  });

  it("6.2 a rejected value keeps the draft and shows the reason", async () => {
    await open(
      state(view("nethernet", OS), () => ({
        ...ACCEPTED,
        ok: false,
        errors: [
          {
            key: "server-udp-ports",
            severity: "error",
            message: "range '19159-19140' starts after it ends",
          },
        ],
      })),
    );

    await userEvent.click(screen.getByRole("radio", { name: "Pin a range" }));
    await userEvent.type(screen.getByLabelText("From port"), "19159");
    await userEvent.type(screen.getByLabelText("To port"), "19140");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/starts after it ends/)).toBeInTheDocument();
    expect((screen.getByLabelText("From port") as HTMLInputElement).value).toBe("19159");
    expect((screen.getByLabelText("To port") as HTMLInputElement).value).toBe("19140");
  });

  it("6.3 saving while running offers the restart", async () => {
    const running = { ...BASE, run_state: "running" };
    const s = state(view("nethernet", OS), () => {
      s.network = view("nethernet", RANGE);
      s.pending = [{ key: "server-udp-ports", saved: "19140-19159", in_effect: null }];
      return ACCEPTED;
    });
    await open(s, running);

    await userEvent.click(screen.getByRole("radio", { name: "Pin a range" }));
    await userEvent.type(screen.getByLabelText("From port"), "19140");
    await userEvent.type(screen.getByLabelText("To port"), "19159");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    push({ ...running, config: { pending: true, pending_count: 1 } });

    const panel = await screen.findByLabelText("pending configuration changes");
    expect(
      within(panel).getByRole("button", { name: "Restart now to apply" }),
    ).toBeInTheDocument();
  });

  it("6.3 maintenance shows the settings without a Save button", async () => {
    await open(state(view("nethernet", RANGE)), {
      ...BASE,
      maintenance: { operation: "backing_up", step: null },
    });
    expect(screen.getByLabelText(/Handshake port/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByText(/read-only during maintenance/)).toBeInTheDocument();
  });

  it("6.3 narrowing the range below max-players shows the banner here and in Configuration", async () => {
    const s = state(view("nethernet", RANGE), () => {
      s.network = view(
        "nethernet",
        nethernet({ form: "range", start: 19140, end: 19144, size: 5 }, "19140-19144"),
        [CONFLICT],
      );
      s.conflicts = [CONFLICT];
      return { ...ACCEPTED, warnings: [CONFLICT], conflicts: [CONFLICT] };
    });
    await open(s);
    expect(screen.queryByRole("alert", { name: "configuration conflicts" })).toBeNull();

    const to = screen.getByLabelText("To port");
    await userEvent.clear(to);
    await userEvent.type(to, "19144");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    const banner = await screen.findByRole("alert", { name: "configuration conflicts" });
    expect(within(banner).getByText(/allows 5 UDP ports/)).toBeInTheDocument();

    cleanup();
    renderApp(<Configuration />);
    expect(
      await screen.findByRole("alert", { name: "configuration conflicts" }),
    ).toHaveTextContent(/allows 5 UDP ports/);
  });
});
