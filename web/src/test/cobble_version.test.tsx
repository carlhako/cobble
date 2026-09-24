import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CobbleVersion } from "../api/client";
import { UPGRADE_POLL_MS } from "../api/useCobbleVersion";
import { FakeEventSource } from "./fakeEventSource";

const RELEASE = "https://github.com/carlhako/cobble/releases/tag/v0.5.0";

function version(over: Partial<CobbleVersion> = {}): CobbleVersion {
  return {
    current: "0.4.0",
    latest: "0.4.0",
    update_available: false,
    release_url: "https://github.com/carlhako/cobble/releases/tag/v0.4.0",
    release_name: "v0.4.0",
    published_at: "2026-09-23T01:55:56Z",
    notes: "## What's new\n\n- **Backup history** tabs",
    checked_at: "2026-09-24T01:00:00+00:00",
    check_error: null,
    one_click_available: true,
    manual_command: null,
    upgrade: null,
    ...over,
  };
}

const AVAILABLE = version({
  latest: "0.5.0",
  update_available: true,
  release_url: RELEASE,
  release_name: "v0.5.0",
  published_at: "2026-09-24T00:17:27Z",
  notes: "## Fixes\n\n- NetherNet transport, see [the docs](https://example.test/docs)",
});

type Handler = (init?: RequestInit) => unknown;

// What the rest of the Updates & Backups screen fetches around the card.
const SCREEN_ROUTES: Record<string, unknown> = {
  "GET /api/backups": { backups: [], unhealthy: null },
  "GET /api/backups/history": { history: [] },
  "GET /api/updates/history": { history: [] },
  "GET /api/maintenance/settings": {
    backup_retention: 7,
    backup_enabled: true,
    backup_schedule: { enabled: true, time: "04:00", frequency: "daily", day: null },
    update_schedule: { enabled: true, time: "04:00", frequency: "daily", day: null },
    pre_update_backup_always_on: true,
  },
};

/** Route table keyed by "METHOD /path"; a function value is called per request
 *  (so a test can change answers over time or throw a network error). */
function mockFetch(routes: Record<string, unknown | Handler>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    const entry = routes[key] ?? SCREEN_ROUTES[key];
    if (entry === undefined) return new Response("{}", { status: 200 });
    const body = typeof entry === "function" ? (entry as Handler)(init) : entry;
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function renderShell(path = "/") {
  const { App } = await import("../App");
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("header version badge (7.2)", () => {
  it("is green [x.y.z] when current", async () => {
    mockFetch({ "GET /api/cobble/version": version() });
    await renderShell();
    const badge = await screen.findByRole("link", { name: "[0.4.0]" });
    expect(badge).toHaveClass("version-badge", "is-current");
    expect(badge).toHaveAttribute("href", "/cobble");
  });

  it("is orange [x.y.z update available] linking to the cobble page", async () => {
    mockFetch({ "GET /api/cobble/version": AVAILABLE });
    await renderShell();
    const link = await screen.findByRole("link", { name: "[0.4.0 update available]" });
    expect(link).toHaveClass("version-badge", "is-update");
    expect(link).toHaveAttribute("href", "/cobble");
    expect(link).not.toHaveAttribute("target");
  });

  it("opens the cobble page when clicked", async () => {
    mockFetch({ "GET /api/cobble/version": AVAILABLE });
    await renderShell();
    await userEvent.click(
      await screen.findByRole("link", { name: "[0.4.0 update available]" }),
    );
    expect(
      await screen.findByRole("heading", { name: "cobble (control panel)" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upgrade to 0.5.0" })).toBeInTheDocument();
  });

  it("stays green after a failed check that kept the last result", async () => {
    mockFetch({
      "GET /api/cobble/version": version({ check_error: "release source unreachable" }),
    });
    await renderShell();
    const badge = await screen.findByText("[0.4.0]");
    expect(badge).toHaveClass("version-badge", "is-current");
    expect(screen.queryByText(/unreachable/)).toBeNull();
  });

  it("is plain when availability is unknown, with no error in the header", async () => {
    mockFetch({
      "GET /api/cobble/version": version({
        latest: null,
        release_url: null,
        check_error: "release source unreachable",
      }),
    });
    await renderShell();
    const badge = await screen.findByRole("link", { name: "[0.4.0]" });
    expect(badge).not.toHaveClass("is-current");
    expect(badge).toHaveAttribute("href", "/cobble");
    expect(screen.queryByText(/unreachable/)).toBeNull();
  });

  it("shows nothing when the version cannot be fetched", async () => {
    mockFetch({
      "GET /api/cobble/version": () => {
        throw new TypeError("network down");
      },
    });
    await renderShell();
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(document.querySelector(".version-badge")).toBeNull();
  });

  it("re-polls so a background check is reflected without a refresh", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let answer = version();
    mockFetch({ "GET /api/cobble/version": () => answer });
    await renderShell();
    await screen.findByText("[0.4.0]");
    answer = AVAILABLE;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    });
    expect(
      await screen.findByRole("link", { name: "[0.4.0 update available]" }),
    ).toBeInTheDocument();
  });
});

async function openCobblePage() {
  await renderShell("/cobble");
  await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
  await screen.findByRole("heading", { name: "cobble (control panel)" });
  return screen.findByText("Installed");
}

describe("cobble page", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn(async () => undefined) },
    });
  });

  it("shows versions, checked-at, the GitHub link, and Check now", async () => {
    const fetchFn = mockFetch({
      "GET /api/cobble/version": version(),
      "POST /api/cobble/check": AVAILABLE,
    });
    await openCobblePage();
    expect(screen.getByText("Latest release").nextSibling).toHaveTextContent("0.4.0");
    expect(screen.getByText("Up to date")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View on GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/carlhako/cobble/releases/tag/v0.4.0",
    );

    await userEvent.click(screen.getByRole("button", { name: "Check now" }));
    expect(await screen.findByText("Update available")).toBeInTheDocument();
    expect(fetchFn).toHaveBeenCalledWith(
      "/api/cobble/check",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("offers Upgrade with a confirmation that names the server stop", async () => {
    const fetchFn = mockFetch({
      "GET /api/cobble/version": AVAILABLE,
      "POST /api/cobble/upgrade": {
        ...AVAILABLE,
        upgrade: {
          state: "pending",
          from: "0.4.0",
          to: "0.5.0",
          requested_at: "T",
          finished_at: null,
          error: null,
          log_tail: null,
        },
      },
    });
    await openCobblePage();
    await userEvent.click(
      await screen.findByRole("button", { name: "Upgrade to 0.5.0" }),
    );
    const dialog = screen.getByRole("alertdialog", { name: "confirm cobble upgrade" });
    expect(dialog).toHaveTextContent(/server will be stopped and players disconnected/);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Back up and upgrade" }),
    );

    expect(fetchFn).toHaveBeenCalledWith(
      "/api/cobble/upgrade",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ version: "0.5.0" }),
      }),
    );
    expect(await screen.findByText(/is waiting for the helper/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upgrade to 0.5.0" })).toBeDisabled();
  });

  it("disables Upgrade while maintenance is in progress", async () => {
    mockFetch({ "GET /api/cobble/version": AVAILABLE });
    await openCobblePage();
    const es = FakeEventSource.byUrl("/api/status/stream");
    act(() =>
      es!.emit({
        run_state: "stopped",
        maintenance: { operation: "backing_up", step: "capturing" },
      }),
    );
    expect(
      await screen.findByRole("button", { name: "Upgrade to 0.5.0" }),
    ).toBeDisabled();
  });

  it("shows the manual root command with Copy when the helper is missing", async () => {
    const cmd =
      "curl -fsSL https://github.com/carlhako/cobble/releases/latest/download/install.sh | bash";
    mockFetch({
      "GET /api/cobble/version": {
        ...AVAILABLE,
        one_click_available: false,
        manual_command: cmd,
      },
    });
    await openCobblePage();
    expect(await screen.findByLabelText("manual upgrade command")).toHaveTextContent(cmd);
    expect(screen.queryByRole("button", { name: /Upgrade to/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(cmd);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("shows a failed last upgrade with its output", async () => {
    mockFetch({
      "GET /api/cobble/version": {
        ...AVAILABLE,
        upgrade: {
          state: "failed",
          from: "0.4.0",
          to: "0.5.0",
          requested_at: "T",
          finished_at: "2026-09-24T02:00:00+00:00",
          error: "cobble.tar.gz does not match its published sha256 digest",
          log_tail: "==> downloading",
        },
      },
    });
    await openCobblePage();
    expect(
      await screen.findByText(/does not match its published sha256/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("upgrade output")).toHaveTextContent("==> downloading");
  });

  it("shows a successful last upgrade without output", async () => {
    mockFetch({
      "GET /api/cobble/version": version({
        current: "0.5.0",
        latest: "0.5.0",
        upgrade: {
          state: "succeeded",
          from: "0.4.0",
          to: "0.5.0",
          requested_at: "T",
          finished_at: "2026-09-24T02:00:00+00:00",
          error: null,
          log_tail: "installer noise",
        },
      }),
    });
    await openCobblePage();
    expect(
      await screen.findByText(/Last upgrade: 0.4.0 → 0.5.0, succeeded/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("upgrade output")).toBeNull();
  });
});

describe("release notes on the cobble page", () => {
  it("renders the latest release's notes as Markdown, links opening outside", async () => {
    mockFetch({ "GET /api/cobble/version": AVAILABLE });
    await openCobblePage();
    expect(
      screen.getByRole("heading", { name: "What's new in 0.5.0" }),
    ).toBeInTheDocument();
    // The title is just the tag here, so only the date is shown under the heading.
    expect(screen.getByText(/^Published /)).toBeInTheDocument();
    expect(screen.queryByText(/v0\.5\.0 ·/)).toBeNull();
    const notes = screen.getByLabelText("release notes");
    expect(within(notes).getByRole("heading", { name: "Fixes" })).toBeInTheDocument();
    expect(within(notes).getByRole("listitem")).toHaveTextContent(/NetherNet transport/);
    const link = within(notes).getByRole("link", { name: "the docs" });
    expect(link).toHaveAttribute("href", "https://example.test/docs");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows a release title that says more than the version", async () => {
    mockFetch({
      "GET /api/cobble/version": { ...AVAILABLE, release_name: "The NetherNet fix" },
    });
    await openCobblePage();
    expect(screen.getByText(/^The NetherNet fix · Published /)).toBeInTheDocument();
  });

  it("shows the notes when already on the latest release", async () => {
    mockFetch({ "GET /api/cobble/version": version() });
    await openCobblePage();
    expect(
      screen.getByRole("heading", { name: "What's new in 0.4.0" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("release notes")).toHaveTextContent("Backup history");
  });

  it("says so when the release was published without notes", async () => {
    mockFetch({ "GET /api/cobble/version": { ...AVAILABLE, notes: null } });
    await openCobblePage();
    expect(screen.getByText(/No release notes were published/)).toBeInTheDocument();
    expect(screen.queryByLabelText("release notes")).toBeNull();
    expect(screen.getByRole("link", { name: "View on GitHub" })).toHaveAttribute(
      "href",
      RELEASE,
    );
  });

  it("shows no notes area when no release is known", async () => {
    mockFetch({
      "GET /api/cobble/version": version({
        latest: null,
        release_url: null,
        release_name: null,
        published_at: null,
        notes: null,
      }),
    });
    await openCobblePage();
    expect(screen.getByText("Latest release").nextSibling).toHaveTextContent("unknown");
    expect(screen.queryByRole("heading", { name: /What's new/ })).toBeNull();
    expect(screen.queryByText(/No release notes were published/)).toBeNull();
  });

  it("never renders raw HTML or script from the notes", async () => {
    const alert = vi.fn();
    vi.stubGlobal("alert", alert);
    mockFetch({
      "GET /api/cobble/version": {
        ...AVAILABLE,
        notes:
          'safe text\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">\n\n[x](javascript:alert(3))',
      },
    });
    await openCobblePage();
    const notes = screen.getByLabelText("release notes");
    expect(notes).toHaveTextContent("safe text");
    expect(notes.querySelector("script, img, [onerror]")).toBeNull();
    expect(notes.querySelector('a[href^="javascript"]')).toBeNull();
    expect(alert).not.toHaveBeenCalled();
  });
});

describe("upgrade follow-through (7.4)", () => {
  const original = window.location;
  let reload: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...original, reload },
    });
  });
  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: original });
  });

  const PENDING = {
    ...AVAILABLE,
    upgrade: {
      state: "pending" as const,
      from: "0.4.0",
      to: "0.5.0",
      requested_at: "T",
      finished_at: null,
      error: null,
      log_tail: null,
    },
  };

  it("survives the disconnect and reloads once cobble reports a new version", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let phase: "old" | "down" | "new" = "old";
    mockFetch({
      "GET /api/cobble/version": () => PENDING,
      "GET /health": () => {
        if (phase === "down") throw new TypeError("connection refused");
        return { status: "ok", version: phase === "new" ? "0.5.0" : "0.4.0" };
      },
    });
    await renderShell();
    expect(await screen.findByText(/Upgrading cobble to 0.5.0/)).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS);
    });
    expect(reload).not.toHaveBeenCalled();

    phase = "down";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS * 2);
    });
    expect(reload).not.toHaveBeenCalled();

    phase = "new";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS);
    });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("stops following and shows the failure when the old cobble reports it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let answer: CobbleVersion = PENDING;
    const fetchFn = mockFetch({
      "GET /api/cobble/version": () => answer,
      "GET /health": { status: "ok", version: "0.4.0" },
    });
    await renderShell();
    await screen.findByText(/Upgrading cobble to 0.5.0/);
    answer = {
      ...AVAILABLE,
      upgrade: { ...PENDING.upgrade, state: "failed", error: "installer exited 1" },
    };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS);
    });
    await waitFor(() => expect(screen.queryByText(/Upgrading cobble to/)).toBeNull());
    const healthCalls = () =>
      fetchFn.mock.calls.filter(([url]) => url === "/health").length;
    const before = healthCalls();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPGRADE_POLL_MS * 3);
    });
    expect(healthCalls()).toBe(before);
    expect(reload).not.toHaveBeenCalled();
  });
});
