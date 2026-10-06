import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CobbleSettings, CobbleVersion } from "../api/client";

const NAMES = ["Australia/Brisbane", "Australia/Sydney", "Europe/London", "UTC"];

const OFFSETS: Record<string, string> = {
  "Australia/Brisbane": "+10:00",
  "Australia/Sydney": "+11:00",
  "Europe/London": "+01:00",
  UTC: "+00:00",
};

/** The settings the server would report for a saved zone, on a UTC host. */
function settings(timezone: string | null): CobbleSettings {
  const effective = timezone ?? "UTC";
  return {
    timezone,
    host_timezone: "UTC",
    effective_timezone: effective,
    effective_offset: OFFSETS[effective],
    timezones: NAMES,
  };
}

const VERSION: CobbleVersion = {
  current: "0.4.0",
  latest: "0.4.0",
  update_available: false,
  release_url: null,
  release_name: null,
  published_at: null,
  notes: null,
  checked_at: null,
  check_error: null,
  one_click_available: true,
  manual_command: null,
  upgrade: null,
};

const SCREEN_ROUTES: Record<string, unknown> = {
  "GET /api/cobble/version": VERSION,
  "GET /api/backups": { backups: [], unhealthy: null },
  "GET /api/backups/history": { history: [] },
  "GET /api/updates/history": { history: [] },
};

/** A fake server for /api/cobble/settings that keeps the saved zone. */
function mockServer(initial: string | null = null) {
  let saved = initial;
  const puts: unknown[] = [];
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      });
    if (key === "GET /api/cobble/settings") return json(settings(saved));
    if (key === "PUT /api/cobble/settings") {
      const body = JSON.parse(String(init?.body)) as { timezone: string | null };
      puts.push(body);
      if (body.timezone !== null && !NAMES.includes(body.timezone)) {
        return json({ detail: `timezone '${body.timezone}' is not recognised` }, 422);
      }
      saved = body.timezone;
      return json(settings(saved));
    }
    const route = SCREEN_ROUTES[key];
    return route === undefined ? new Response("{}", { status: 200 }) : json(route);
  });
  vi.stubGlobal("fetch", fn);
  return { puts };
}

function browserZone(zone: string) {
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockReturnValue({
    timeZone: zone,
  } as Intl.ResolvedDateTimeFormatOptions);
}

async function renderShell(path: string) {
  const { App } = await import("../App");
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("cobble settings card", () => {
  it("renders before the version and upgrade content", async () => {
    mockServer();
    browserZone("UTC");
    await renderShell("/cobble");
    const heading = await screen.findByRole("heading", { name: "Settings" });
    const installed = await screen.findByText("Installed");
    expect(
      heading.compareDocumentPosition(installed) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows the effective zone and offset, and names the host in the default option", async () => {
    mockServer("Australia/Brisbane");
    browserZone("Australia/Brisbane");
    await renderShell("/cobble");
    expect(
      await screen.findByText(/Australia\/Brisbane \(UTC\+10:00\)/),
    ).toBeInTheDocument();
    const select = screen.getByRole("combobox", { name: /Timezone/ });
    const options = within(select).getAllByRole("option");
    expect(options[0]).toHaveTextContent("Host default (UTC)");
    expect(select).toHaveValue("Australia/Brisbane");
  });

  it("picking a zone and saving sends a PUT with the name", async () => {
    const server = mockServer();
    browserZone("UTC");
    await renderShell("/cobble");
    const select = await screen.findByRole("combobox", { name: /Timezone/ });
    await userEvent.selectOptions(select, "Australia/Brisbane");
    await userEvent.click(screen.getByRole("button", { name: "Save timezone" }));
    await waitFor(() =>
      expect(server.puts).toEqual([{ timezone: "Australia/Brisbane" }]),
    );
    expect(
      await screen.findByText(/Australia\/Brisbane \(UTC\+10:00\)/),
    ).toBeInTheDocument();
  });

  it("the host default sends null", async () => {
    const server = mockServer("Europe/London");
    browserZone("Europe/London");
    await renderShell("/cobble");
    const select = await screen.findByRole("combobox", { name: /Timezone/ });
    await waitFor(() => expect(select).toHaveValue("Europe/London"));
    await userEvent.selectOptions(select, "");
    await userEvent.click(screen.getByRole("button", { name: "Save timezone" }));
    await waitFor(() => expect(server.puts).toEqual([{ timezone: null }]));
    expect(await screen.findByText(/UTC \(UTC\+00:00\)/)).toBeInTheDocument();
    expect(screen.getByText(/the host's timezone/)).toBeInTheDocument();
  });

  it("filters the zone list by name", async () => {
    mockServer();
    browserZone("UTC");
    await renderShell("/cobble");
    const select = await screen.findByRole("combobox", { name: /Timezone/ });
    await userEvent.type(screen.getByRole("searchbox"), "austr");
    const shown = within(select)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(shown).toEqual([
      "Host default (UTC)",
      "Australia/Brisbane",
      "Australia/Sydney",
    ]);
  });

  it("shows a rejection's message", async () => {
    mockServer();
    browserZone("UTC");
    await renderShell("/cobble");
    const select = await screen.findByRole("combobox", { name: /Timezone/ });
    // A name the picker would not offer, but the server can still refuse.
    const option = document.createElement("option");
    option.value = "Mars/Olympus_Mons";
    option.textContent = "Mars/Olympus_Mons";
    select.appendChild(option);
    await userEvent.selectOptions(select, "Mars/Olympus_Mons");
    await userEvent.click(screen.getByRole("button", { name: "Save timezone" }));
    expect(
      await screen.findByText("timezone 'Mars/Olympus_Mons' is not recognised"),
    ).toBeInTheDocument();
  });

  it("the browser-zone button sets the browser's zone", async () => {
    const server = mockServer();
    browserZone("Australia/Brisbane");
    await renderShell("/cobble");
    const button = await screen.findByRole("button", {
      name: "Use my browser's timezone (Australia/Brisbane)",
    });
    await userEvent.click(button);
    await waitFor(() =>
      expect(server.puts).toEqual([{ timezone: "Australia/Brisbane" }]),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /Use my browser's timezone/ }),
      ).not.toBeInTheDocument(),
    );
  });

  it("offers no browser-zone button when the zones are the same", async () => {
    mockServer();
    browserZone("UTC");
    await renderShell("/cobble");
    await screen.findByRole("combobox", { name: /Timezone/ });
    expect(
      screen.queryByRole("button", { name: /Use my browser's timezone/ }),
    ).not.toBeInTheDocument();
  });
});

describe("timezone mismatch notice", () => {
  it("is shown on Updates & Backups and offers the switch", async () => {
    const server = mockServer();
    browserZone("Australia/Brisbane");
    await renderShell("/updates");
    const notice = await screen.findByText(/Schedules run in UTC time/);
    expect(notice.closest(".tz-mismatch")).toHaveTextContent(
      "This browser is in Australia/Brisbane",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Switch cobble to Australia/Brisbane" }),
    );
    await waitFor(() =>
      expect(server.puts).toEqual([{ timezone: "Australia/Brisbane" }]),
    );
    await waitFor(() =>
      expect(screen.queryByText(/Schedules run in/)).not.toBeInTheDocument(),
    );
  });

  it("is also shown in the cobble Settings card", async () => {
    mockServer();
    browserZone("Australia/Brisbane");
    await renderShell("/cobble");
    expect(await screen.findByText(/Schedules run in UTC time/)).toBeInTheDocument();
  });

  it("is not shown for zones that keep the same clock time all year", async () => {
    mockServer("Australia/Sydney");
    browserZone("Australia/Melbourne");
    await renderShell("/updates");
    await screen.findByRole("heading", { name: "Updates & Backups" });
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/cobble/settings", expect.anything()),
    );
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText(/Schedules run in/)).not.toBeInTheDocument();
  });

  it("a dismissal hides it for that pair, and a changed pair shows it again", async () => {
    mockServer();
    browserZone("Australia/Brisbane");
    const first = await renderShell("/updates");
    await screen.findByText(/Schedules run in UTC time/);
    await userEvent.click(screen.getByRole("button", { name: "dismiss" }));
    expect(screen.queryByText(/Schedules run in/)).not.toBeInTheDocument();
    first.unmount();

    // The same pair, in a fresh page load: still dismissed.
    const second = await renderShell("/updates");
    await screen.findByRole("heading", { name: "Updates & Backups" });
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByText(/Schedules run in/)).not.toBeInTheDocument();
    second.unmount();

    // The browser's zone changed: a different pair, so the notice returns.
    browserZone("Asia/Tokyo");
    await renderShell("/updates");
    expect(await screen.findByText(/Schedules run in UTC time/)).toBeInTheDocument();
  });

  it("still renders the page when storage throws", async () => {
    mockServer();
    browserZone("Australia/Brisbane");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    await renderShell("/updates");
    expect(await screen.findByText(/Schedules run in UTC time/)).toBeInTheDocument();
    // Dismissing cannot be saved, but it still hides the notice for this view.
    await userEvent.click(screen.getByRole("button", { name: "dismiss" }));
    expect(screen.queryByText(/Schedules run in/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Updates & Backups" }),
    ).toBeInTheDocument();
  });
});
