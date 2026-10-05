import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RESTART_POLL_MS, useCobbleRestart } from "../api/useCobbleRestart";

// import-backup-archive 6.2: following cobble's restart after a restore.
describe("useCobbleRestart", () => {
  const original = window.location;
  let reload: ReturnType<typeof vi.fn>;
  let phase: "old" | "down" | "back";

  beforeEach(() => {
    reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...original, reload },
    });
    phase = "old";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        if (phase === "down") throw new TypeError("connection refused");
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }),
    );
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    Object.defineProperty(window, "location", { configurable: true, value: original });
  });

  it("reloads only after cobble went away and came back", async () => {
    const { result } = renderHook(() => useCobbleRestart());
    expect(result.current.restarting).toBe(false);
    act(() => result.current.begin());
    expect(result.current.restarting).toBe(true);

    // the old process still answering is not "back"
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESTART_POLL_MS * 2);
    });
    expect(reload).not.toHaveBeenCalled();

    phase = "down";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESTART_POLL_MS * 2);
    });
    expect(reload).not.toHaveBeenCalled();

    phase = "back";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESTART_POLL_MS);
    });
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not poll until a restart begins", async () => {
    renderHook(() => useCobbleRestart());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RESTART_POLL_MS * 3);
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
