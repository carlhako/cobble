import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Console } from "../sections/Console";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

function pushStatus(runState: string) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() =>
    es.emit({
      run_state: runState,
      version: "1.2.3.4",
      uptime_seconds: runState === "running" ? 1 : null,
      online_players: [],
      players_incomplete: false,
      last_shutdown: null,
    }),
  );
}

function pushConsole(line: { seq: number; kind: string; text: string }) {
  const es = FakeEventSource.byUrl("/api/console/stream");
  if (!es) throw new Error("console stream not opened");
  act(() => es.emit(line));
}

afterEach(() => vi.unstubAllGlobals());

describe("Console (8.5)", () => {
  it("disables command input when the server is not running", async () => {
    renderApp(<Console />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    pushStatus("stopped");
    expect(await screen.findByLabelText("console command")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("streams output and shows a submitted command and its response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    renderApp(<Console />);
    await waitFor(() =>
      expect(FakeEventSource.byUrl("/api/console/stream")).toBeTruthy(),
    );
    pushStatus("running");
    pushConsole({ seq: 1, kind: "output", text: "[INFO] Server started." });
    expect(await screen.findByText("[INFO] Server started.")).toBeInTheDocument();

    const input = screen.getByLabelText("console command");
    await userEvent.type(input, "list");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/console/command",
      expect.objectContaining({ method: "POST" }),
    );
    // server echoes the command and its response into the stream
    pushConsole({ seq: 2, kind: "command", text: "list" });
    pushConsole({ seq: 3, kind: "output", text: "There are 0/10 players online" });
    expect(await screen.findByText("> list")).toBeInTheDocument();
    expect(screen.getByText("There are 0/10 players online")).toBeInTheDocument();
  });

  it("de-duplicates replayed history on reconnect by sequence number", async () => {
    renderApp(<Console />);
    await waitFor(() =>
      expect(FakeEventSource.byUrl("/api/console/stream")).toBeTruthy(),
    );
    pushStatus("running");
    pushConsole({ seq: 1, kind: "output", text: "line one" });
    pushConsole({ seq: 2, kind: "output", text: "line two" });
    // reconnect replays seq 1..2 then continues
    pushConsole({ seq: 1, kind: "output", text: "line one" });
    pushConsole({ seq: 2, kind: "output", text: "line two" });
    pushConsole({ seq: 3, kind: "output", text: "line three" });
    await screen.findByText("line three");
    expect(screen.getAllByText("line one")).toHaveLength(1);
  });
});
