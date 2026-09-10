import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportWorld } from "../sections/ImportWorld";
import { sections } from "../sections";
import { FakeEventSource } from "./fakeEventSource";
import { renderApp } from "./util";

// -- a controllable XMLHttpRequest for the D10 upload path --------
type XhrPlan = {
  progress?: number[];
  status?: number;
  response?: unknown;
  fail?: "error" | "abort";
};
let xhrPlan: XhrPlan = { progress: [0.5, 1], status: 200, response: {} };
const xhrSent: unknown[] = [];

class FakeXHR {
  upload = { onprogress: null as null | ((e: ProgressEvent) => void) };
  onload: null | (() => void) = null;
  onerror: null | (() => void) = null;
  onabort: null | (() => void) = null;
  status = 0;
  statusText = "";
  response: unknown = null;
  responseType = "";
  open = vi.fn();
  setRequestHeader = vi.fn();
  abort = vi.fn(() => this.onabort?.());
  send = vi.fn((body: unknown) => {
    xhrSent.push(body);
    queueMicrotask(() => {
      for (const p of xhrPlan.progress ?? []) {
        this.upload.onprogress?.({ lengthComputable: true, loaded: p, total: 1 } as ProgressEvent);
      }
      if (xhrPlan.fail === "error") return this.onerror?.();
      if (xhrPlan.fail === "abort") return this.onabort?.();
      this.status = xhrPlan.status ?? 200;
      this.response = xhrPlan.response ?? {};
      this.onload?.();
    });
  });
}

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

const EMPTY_VIEW = {
  held: false,
  inspection: null,
  refusal: null,
  version: null,
  current_world: "Bedrock level",
};

const HELD_OLDER = {
  held: true,
  refusal: null,
  current_world: "Bedrock level",
  inspection: {
    world_name: "Crafty World",
    world_prefix: "worlds/Crafty World/",
    uncompressed_size: 21 * 1024 * 1024,
    seed: "-7302393117572340386",
    last_opened_version: "1.26.43.1",
    extra_server_files: ["server.properties", "allowlist.json", "permissions.json"],
  },
  version: {
    installed: "1.99.0.1",
    world: "1.26.43.1",
    relation: "older",
    importable: true,
  },
};

const BASE_STATUS = {
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
  version_info: null,
  update: null,
  backup: null,
  config: null,
  gamerules: null,
  access: null,
};

function push(data: unknown) {
  const es = FakeEventSource.byUrl("/api/status/stream");
  if (!es) throw new Error("status stream not opened");
  act(() => es.emit(data));
}

afterEach(() => {
  vi.unstubAllGlobals();
  xhrPlan = { progress: [0.5, 1], status: 200, response: {} };
  xhrSent.length = 0;
});

async function file(name = "world.zip"): Promise<File> {
  return new File([new Uint8Array(16)], name, { type: "application/zip" });
}

describe("Import World section", () => {
  // -- 6.1 --------------------------------------------------------
  it("6.1 is registered as a section and its route resolves", async () => {
    expect(sections.map((s) => s.path)).toContain("/import");
    expect(sections.find((s) => s.path === "/import")?.label).toBe("Import World");
    mockFetch({ "GET /api/import": EMPTY_VIEW });
    renderApp(<ImportWorld />);
    expect(await screen.findByRole("heading", { name: "Import World" })).toBeInTheDocument();
  });

  // -- 6.2 --------------------------------------------------------
  it("6.2 upload uses XHR progress; other calls use the shared fetch wrapper", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest);
    xhrPlan = { progress: [0.25, 1], status: 200, response: HELD_OLDER };
    const fetchFn = mockFetch({ "GET /api/import": EMPTY_VIEW });
    renderApp(<ImportWorld />);
    await screen.findByRole("heading", { name: "Import World" });

    await userEvent.upload(screen.getByLabelText("world archive"), await file());
    // the held archive returned by the XHR is reflected
    expect(await screen.findByText("Archive contents")).toBeInTheDocument();
    // the GET went through fetch, the upload did not
    expect(fetchFn).toHaveBeenCalledWith("/api/import", expect.anything());
    expect(
      fetchFn.mock.calls.some(([u]) => String(u).includes("/api/import/upload")),
    ).toBe(false);
    expect(xhrSent).toHaveLength(1);
  });

  // -- 6.3 --------------------------------------------------------
  it("6.3 states the import is destructive and a failed upload can be retried", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXHR as unknown as typeof XMLHttpRequest);
    xhrPlan = { fail: "error" };
    mockFetch({ "GET /api/import": EMPTY_VIEW });
    renderApp(<ImportWorld />);
    await screen.findByRole("heading", { name: "Import World" });
    expect(screen.getByText(/Importing replaces/i)).toBeInTheDocument();

    await userEvent.upload(screen.getByLabelText("world archive"), await file());
    expect(await screen.findByRole("alert")).toHaveTextContent(/Upload failed/i);
    // input is usable again for a retry
    expect(screen.getByLabelText("world archive")).toBeEnabled();
  });

  // -- 6.4 --------------------------------------------------------
  it("6.4 shows world name, size, seed, version, and lists non-world files", async () => {
    mockFetch({ "GET /api/import": HELD_OLDER });
    renderApp(<ImportWorld />);
    expect(await screen.findByText("Crafty World")).toBeInTheDocument();
    expect(screen.getByText("21.0 MB")).toBeInTheDocument();
    expect(screen.getByText("-7302393117572340386")).toBeInTheDocument();
    expect(screen.getByText("1.26.43.1")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("server.properties");
    expect(screen.getByRole("note")).toHaveTextContent("will not be imported");
  });

  // -- 6.5 --------------------------------------------------------
  it.each([
    "no Bedrock world was found in the archive",
    "the archive is ambiguous: it contains 2 Bedrock worlds",
    "the uploaded file is not a readable archive: File is not a zip file",
  ])("6.5 shows the refusal %s and offers no apply", async (refusal) => {
    mockFetch({
      "GET /api/import": { ...EMPTY_VIEW, held: true, refusal },
    });
    renderApp(<ImportWorld />);
    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import this world" })).toBeNull();
  });

  // -- 6.6 --------------------------------------------------------
  it("6.6 confirmation names both worlds and nothing applies until confirmed", async () => {
    const fetchFn = mockFetch({ "GET /api/import": { ...HELD_OLDER, version: { ...HELD_OLDER.version, relation: "same" } } });
    renderApp(<ImportWorld />);
    await userEvent.click(await screen.findByRole("button", { name: "Import this world" }));

    const dialog = await screen.findByRole("alertdialog", { name: "confirm import" });
    expect(dialog).toHaveTextContent("Crafty World");
    expect(dialog).toHaveTextContent("Bedrock level");
    expect(dialog).toHaveTextContent(/stopped and restarted/i);
    expect(dialog).toHaveTextContent(/backup of/i);
    expect(fetchFn.mock.calls.some(([u, i]) => String(u).includes("apply") && i)).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    // still held, still no apply call
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(fetchFn.mock.calls.some(([u]) => String(u).includes("apply"))).toBe(false);
  });

  // -- 6.7 --------------------------------------------------------
  it("6.7 an older world takes a second confirmation", async () => {
    mockFetch({
      "GET /api/import": HELD_OLDER,
      "POST /api/import/apply": {
        ok: false,
        at: "t",
        world: "Bedrock level",
        replaced_capture: null,
        needs_confirmation: true,
        warning: "the world was last opened with Bedrock 1.26.43.1, older than the installed 1.99.0.1",
        error: null,
      },
    });
    renderApp(<ImportWorld />);
    await userEvent.click(await screen.findByRole("button", { name: "Import this world" }));
    await userEvent.click(screen.getByRole("button", { name: "Stop the server and import" }));
    expect(
      await screen.findByRole("alertdialog", { name: "confirm older-world import" }),
    ).toHaveTextContent(/older than the installed/i);
  });

  it("6.7 a newer world offers no apply action and names both versions", async () => {
    mockFetch({
      "GET /api/import": {
        ...HELD_OLDER,
        version: { installed: "1.20.0.1", world: "1.30.0.1", relation: "newer", importable: false },
      },
    });
    renderApp(<ImportWorld />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("1.20.0.1");
    expect(alert).toHaveTextContent("1.30.0.1");
    expect(alert).toHaveTextContent(/A newer world cannot be imported/i);
    expect(screen.queryByRole("button", { name: "Import this world" })).toBeNull();
  });

  // -- 6.8 --------------------------------------------------------
  it("6.8 reflects import stages and names the safety capture on completion", async () => {
    mockFetch({
      "GET /api/import": { ...HELD_OLDER, version: { ...HELD_OLDER.version, relation: "same" } },
      "POST /api/import/apply": {
        ok: true,
        at: "t",
        world: "Bedrock level",
        replaced_capture: "cobble-backup-20260909T120000.000000Z.tar.gz",
        needs_confirmation: false,
        warning: null,
        error: null,
      },
    });
    renderApp(<ImportWorld />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE_STATUS, maintenance: null });

    // live stage while the import runs
    push({
      ...BASE_STATUS,
      maintenance: { operation: "importing", step: "putting the world in place" },
    });
    expect(await screen.findByText(/putting the world in place/)).toBeInTheDocument();
    push({ ...BASE_STATUS, maintenance: null });

    await userEvent.click(await screen.findByRole("button", { name: "Import this world" }));
    await userEvent.click(screen.getByRole("button", { name: "Stop the server and import" }));
    expect(
      await screen.findByText(/cobble-backup-20260909T120000\.000000Z\.tar\.gz/),
    ).toBeInTheDocument();
  });

  it("6.8 names the safety capture when an import fails mid-extract", async () => {
    mockFetch({
      "GET /api/import": { ...HELD_OLDER, version: { ...HELD_OLDER.version, relation: "same" } },
      "POST /api/import/apply": {
        ok: false,
        at: "t",
        world: "Bedrock level",
        replaced_capture: "cobble-backup-SAFETY.tar.gz",
        needs_confirmation: false,
        warning: null,
        error: "import failed partway through: disk error; the replaced world is saved as cobble-backup-SAFETY.tar.gz",
      },
    });
    renderApp(<ImportWorld />);
    await userEvent.click(await screen.findByRole("button", { name: "Import this world" }));
    await userEvent.click(screen.getByRole("button", { name: "Stop the server and import" }));
    expect(await screen.findByText(/Import failed/)).toBeInTheDocument();
    expect(screen.getAllByText(/cobble-backup-SAFETY\.tar\.gz/).length).toBeGreaterThan(0);
  });

  // -- 6.9 --------------------------------------------------------
  it("6.9 disables applying while another maintenance operation runs", async () => {
    mockFetch({ "GET /api/import": { ...HELD_OLDER, version: { ...HELD_OLDER.version, relation: "same" } } });
    renderApp(<ImportWorld />);
    await waitFor(() => expect(FakeEventSource.byUrl("/api/status/stream")).toBeTruthy());
    push({ ...BASE_STATUS, maintenance: { operation: "backing_up", step: "capturing" } });

    expect(await screen.findByText(/A backup is in progress/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import this world" })).toBeDisabled();
  });
});
