import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusProvider } from "../api/StatusContext";
import { usePlayerSessions } from "../api/usePlayerSessions";
import { FakeEventSource } from "./fakeEventSource";

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

const SESSIONS = { xuid: "alex", gamertag: "Alex", sessions: [] };

function mockFetch() {
  const fn = vi.fn(
    async (_url: string, _init?: RequestInit) =>
      new Response(JSON.stringify(SESSIONS), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

function wrapper({ children }: { children: ReactNode }) {
  return <StatusProvider>{children}</StatusProvider>;
}

function pushStatus(data: unknown) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() => es.emit(data));
}

const sessionCalls = (fn: ReturnType<typeof mockFetch>) =>
  fn.mock.calls.filter((c) => c[0] === "/api/players/alex/sessions").length;

afterEach(() => vi.unstubAllGlobals());

describe("usePlayerSessions", () => {
  it("1.1 fetches once when an id is selected and refetches on reload()", async () => {
    const fetchFn = mockFetch();
    const { result, rerender } = renderHook(({ id }) => usePlayerSessions(id), {
      wrapper,
      initialProps: { id: null as string | null },
    });

    // No id -> no fetch.
    expect(sessionCalls(fetchFn)).toBe(0);

    rerender({ id: "alex" });
    await waitFor(() => expect(result.current.sessions).toEqual(SESSIONS));
    expect(sessionCalls(fetchFn)).toBe(1);

    // An unrelated re-render does not refetch.
    rerender({ id: "alex" });
    expect(sessionCalls(fetchFn)).toBe(1);

    act(() => result.current.reload());
    await waitFor(() => expect(sessionCalls(fetchFn)).toBe(2));
  });

  it("1.2 refetches when the status stream signals a ban-count change", async () => {
    const fetchFn = mockFetch();
    const { result, rerender } = renderHook(({ id }) => usePlayerSessions(id), {
      wrapper,
      initialProps: { id: null as string | null },
    });
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    rerender({ id: "alex" });
    await waitFor(() => expect(result.current.sessions).toEqual(SESSIONS));

    // Settle on a known status baseline (the first frame moves the signature
    // off its null starting value, as the roster and access feeds also do).
    pushStatus(BASE_STATUS);
    await waitFor(() => expect(sessionCalls(fetchFn)).toBeGreaterThanOrEqual(1));
    const settled = sessionCalls(fetchFn);

    // A repeat frame with no relevant change does not refetch.
    pushStatus(BASE_STATUS);
    expect(sessionCalls(fetchFn)).toBe(settled);

    // A frame that bumps the ban count triggers a refetch.
    pushStatus({ ...BASE_STATUS, access: { ...BASE_STATUS.access, ban_count: 1 } });
    await waitFor(() => expect(sessionCalls(fetchFn)).toBe(settled + 1));

    // ...and that new signature is itself stable.
    pushStatus({ ...BASE_STATUS, access: { ...BASE_STATUS.access, ban_count: 1 } });
    expect(sessionCalls(fetchFn)).toBe(settled + 1);
  });
});
