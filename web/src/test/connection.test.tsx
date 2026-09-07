import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "../App";
import { FakeEventSource } from "./fakeEventSource";

const STATUS_URL = "/api/status/stream";

function emit(url: string, data: unknown) {
  const es = FakeEventSource.byUrl(url);
  if (!es) throw new Error(`${url} not opened`);
  act(() => es.emit(data));
}

describe("live-connection layer (8.2)", () => {
  it("shows a disconnected indicator on connection loss and clears it on reconnect", async () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    await waitFor(() => expect(FakeEventSource.byUrl(STATUS_URL)).toBeTruthy());
    emit(STATUS_URL, {
      run_state: "running",
      version: "1.2.3.4",
      uptime_seconds: 5,
      online_players: [],
      players_incomplete: false,
      last_shutdown: null,
    });
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.queryByText(/Disconnected from cobble/)).toBeNull();

    // connection drops
    act(() => FakeEventSource.byUrl(STATUS_URL)!.fail());
    expect(await screen.findByText(/Disconnected from cobble/)).toBeInTheDocument();

    // the hook retries: a new EventSource for the same URL is created and opens
    await waitFor(
      () => {
        const all = FakeEventSource.instances.filter((i) => i.url === STATUS_URL);
        expect(all.length).toBeGreaterThan(1);
      },
      { timeout: 3000 },
    );
    emit(STATUS_URL, {
      run_state: "stopped",
      version: "1.2.3.4",
      uptime_seconds: null,
      online_players: [],
      players_incomplete: false,
      last_shutdown: null,
    });
    await waitFor(() =>
      expect(screen.queryByText(/Disconnected from cobble/)).toBeNull(),
    );
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
  });
});
