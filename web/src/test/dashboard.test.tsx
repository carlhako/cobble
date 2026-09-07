import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Dashboard } from "../sections/Dashboard";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

function push(data: unknown) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() => es.emit(data));
}

const RUNNING = {
  run_state: "running",
  version: "1.2.3.4",
  uptime_seconds: 3661,
  online_players: [{ xuid: "555", gamertag: "Alex" }],
  players_incomplete: false,
  last_shutdown: { clean: false, at: "2024-01-01T00:00:00Z" },
};

describe("Dashboard (8.3, 8.4)", () => {
  it("renders run state, version, uptime, players and last-shutdown from a live frame", async () => {
    renderApp(<Dashboard />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(RUNNING);

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText("1.2.3.4")).toBeInTheDocument();
    expect(screen.getByText("1h 1m 1s")).toBeInTheDocument();
    expect(screen.getByText("Alex")).toBeInTheDocument();
    expect(screen.getByText(/Unclean/)).toBeInTheDocument();
  });

  it("updates when a new frame arrives, with no user action", async () => {
    renderApp(<Dashboard />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push(RUNNING);
    expect(await screen.findByText("Running")).toBeInTheDocument();

    push({ ...RUNNING, run_state: "stopped", uptime_seconds: null, online_players: [] });
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
  });

  it("offers only actions valid for the current state", async () => {
    renderApp(<Dashboard />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());

    push(RUNNING);
    await screen.findByText("Running");
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restart" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start" })).toBeNull();

    push({ ...RUNNING, run_state: "starting" });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Start" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Restart" })).toBeNull();
    });
  });
});
