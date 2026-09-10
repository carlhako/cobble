import { useCallback, useEffect, useRef, useState } from "react";
import { useStatus } from "../api/StatusContext";
import {
  ApiCallError,
  api,
  uploadWorldArchive,
  type ImportOutcome,
  type ImportView,
} from "../api/client";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

const MAINTENANCE_LABEL: Record<string, string> = {
  updating: "An update",
  restoring: "A restore",
  backing_up: "A backup",
  importing: "An import",
};

/** 6.4 — what cobble found in the held archive. */
function InspectionPanel({ view }: { view: ImportView }) {
  const insp = view.inspection;
  if (!insp) return null;
  return (
    <div className="panel">
      <h2>Archive contents</h2>
      <div className="cards">
        <div className="card">
          <div className="card-label">World</div>
          <div className="card-value">{insp.world_name ?? "(unnamed)"}</div>
        </div>
        <div className="card">
          <div className="card-label">Size</div>
          <div className="card-value">{fmtBytes(insp.uncompressed_size)}</div>
        </div>
        <div className="card">
          <div className="card-label">Seed</div>
          <div className="card-value">{insp.seed ?? "unknown"}</div>
        </div>
        <div className="card">
          <div className="card-label">Last opened with</div>
          <div className="card-value">{insp.last_opened_version ?? "unknown"}</div>
        </div>
      </div>
      {insp.extra_server_files.length > 0 && (
        <p className="muted" role="note">
          The archive also contains {insp.extra_server_files.join(", ")}. These are
          present but will not be imported — the server keeps its own configuration,
          allowlist, and permissions.
        </p>
      )}
    </div>
  );
}

/** 6.6 + 6.7 — confirmation(s) before anything destructive happens. */
function ConfirmPanel({
  view,
  stage,
  working,
  onConfirm,
  onCancel,
}: {
  view: ImportView;
  stage: "primary" | "old";
  working: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const installing = view.inspection?.world_name ?? "the archived world";
  if (stage === "old") {
    return (
      <div className="panel is-warn confirm-restore" role="alertdialog" aria-label="confirm older-world import">
        <strong>This world is older than the installed server.</strong>
        <p>
          It was last opened with Bedrock {view.version?.world}, older than the installed{" "}
          {view.version?.installed}. Importing it lets the installed server upgrade the world
          in place, which cannot be undone.
        </p>
        <div className="controls-row">
          <button className="btn btn-stop" disabled={working} onClick={onConfirm}>
            {working ? "Importing…" : "Upgrade and import anyway"}
          </button>
          <button className="btn" disabled={working} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="panel is-warn confirm-restore" role="alertdialog" aria-label="confirm import">
      <strong>Import this world?</strong>
      <p>
        <code>{installing}</code> will replace <code>{view.current_world}</code>, the world the
        server currently loads.
      </p>
      <ul className="muted">
        <li>The server will be stopped and restarted.</li>
        <li>A backup of <code>{view.current_world}</code> is captured first, so the import can be undone.</li>
      </ul>
      <div className="controls-row">
        <button className="btn btn-stop" disabled={working} onClick={onConfirm}>
          {working ? "Importing…" : "Stop the server and import"}
        </button>
        <button className="btn" disabled={working} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export function ImportWorld() {
  const { status } = useStatus();
  const [view, setView] = useState<ImportView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [progress, setProgress] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [confirmStage, setConfirmStage] = useState<null | "primary" | "old">(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ImportOutcome | null>(null);

  const reload = useCallback(async () => {
    try {
      setView(await api.importGet());
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof ApiCallError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const maintenance = status?.maintenance ?? null;
  // 6.9 — another maintenance operation blocks applying an import. An import's
  // own "importing" maintenance is the running import and is shown as progress.
  const blockingOp =
    maintenance && maintenance.operation !== "importing" ? maintenance.operation : null;
  const importInFlight = applying || maintenance?.operation === "importing";

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadError(null);
    setOutcome(null);
    setProgress(0);
    const { promise, abort } = uploadWorldArchive(file, setProgress);
    abortRef.current = abort;
    try {
      setView(await promise);
    } catch (err) {
      setUploadError(err instanceof ApiCallError ? `${err.code}: ${err.message}` : String(err));
    } finally {
      setProgress(null);
      abortRef.current = null;
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const runApply = async (confirmOldVersion: boolean) => {
    setApplying(true);
    setApplyError(null);
    try {
      const result = await api.importApply(confirmOldVersion);
      if (result.needs_confirmation) {
        setConfirmStage("old");
      } else {
        setOutcome(result);
        setConfirmStage(null);
        if (!result.ok) setApplyError(result.error ?? "import failed");
      }
      await reload();
    } catch (e) {
      setApplyError(e instanceof ApiCallError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setApplying(false);
    }
  };

  const rel = view?.version?.relation;
  const canApply = !!view?.held && !view.refusal && !!view.inspection && rel !== "newer";

  return (
    <section className="section import-world">
      <h1>Import World</h1>

      {blockingOp && (
        <div className="panel is-busy" role="status">
          <strong>{MAINTENANCE_LABEL[blockingOp] ?? "An operation"} is in progress.</strong>
          <div className="muted">Importing is unavailable until it finishes.</div>
        </div>
      )}

      {/* 6.3 — upload */}
      <div className="panel">
        <h2>Upload a world archive</h2>
        <p className="muted">
          Importing replaces <code>{view?.current_world ?? "the world the server currently loads"}</code>.
          The archive may be a full server backup, a zipped world folder, or a
          <code>.mcworld</code> export.
        </p>
        <input
          ref={fileRef}
          type="file"
          aria-label="world archive"
          accept=".zip,.mcworld"
          disabled={progress !== null || importInFlight}
          onChange={onFile}
        />
        {progress !== null && (
          <div className="upload-progress">
            <progress value={progress} max={1} aria-label="upload progress" />
            <span className="muted"> {Math.round(progress * 100)}%</span>
            <button className="link" onClick={() => abortRef.current?.()}>
              cancel
            </button>
          </div>
        )}
        {uploadError && (
          <div className="controls-error" role="alert">
            Upload failed: {uploadError}. Choose the file again to retry.
          </div>
        )}
        {loadError && <div className="controls-error">{loadError}</div>}
      </div>

      {/* 6.5 — a refused archive: reason, no apply */}
      {view?.held && view.refusal && (
        <div className="panel is-error" role="alert">
          <strong>This archive cannot be imported.</strong>
          <p>{view.refusal}</p>
          <button className="btn" onClick={() => void api.importDiscard().then(setView)}>
            Discard
          </button>
        </div>
      )}

      {view?.held && view.inspection && (
        <>
          <InspectionPanel view={view} />

          {/* 6.7 — a newer world is refused outright, no apply action */}
          {rel === "newer" ? (
            <div className="panel is-error" role="alert">
              <strong>This world is newer than the installed server.</strong>
              <p>
                It was last opened with Bedrock {view.version?.world}, newer than the installed{" "}
                {view.version?.installed}. A newer world cannot be imported — update the server
                first.
              </p>
              <button className="btn" onClick={() => void api.importDiscard().then(setView)}>
                Discard
              </button>
            </div>
          ) : (
            <div className="panel">
              <h2>Apply</h2>
              {confirmStage ? (
                <ConfirmPanel
                  view={view}
                  stage={confirmStage}
                  working={applying}
                  onConfirm={() => void runApply(confirmStage === "old")}
                  onCancel={() => setConfirmStage(null)}
                />
              ) : (
                <div className="controls-row">
                  <button
                    className="btn btn-stop"
                    disabled={!canApply || !!blockingOp || importInFlight}
                    onClick={() => setConfirmStage("primary")}
                  >
                    Import this world
                  </button>
                  <button
                    className="btn"
                    disabled={importInFlight}
                    onClick={() => void api.importDiscard().then(setView)}
                  >
                    Discard
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* 6.8 — live stages and the outcome */}
      {importInFlight && maintenance?.operation === "importing" && (
        <div className="panel is-busy" role="status">
          <strong>Import in progress</strong>
          {maintenance.step && <span className="muted"> · {maintenance.step}</span>}
        </div>
      )}

      {outcome && (
        <div className={`panel ${outcome.ok ? "is-ok" : "is-error"}`} role="status">
          {outcome.ok ? (
            <>
              <strong>Import complete.</strong>
              <p>
                <code>{outcome.world}</code> now holds the imported world.
                {outcome.replaced_capture && (
                  <>
                    {" "}
                    The previous world was saved as <code>{outcome.replaced_capture}</code> and can
                    be restored from Updates &amp; Backups.
                  </>
                )}
              </p>
            </>
          ) : (
            <>
              <strong>Import failed.</strong>
              <p>{outcome.error}</p>
              {outcome.replaced_capture && (
                <p>
                  The world being replaced is saved as <code>{outcome.replaced_capture}</code> and
                  can be restored from Updates &amp; Backups.
                </p>
              )}
            </>
          )}
        </div>
      )}
      {applyError && !outcome && (
        <div className="controls-error" role="alert">
          {applyError}
        </div>
      )}
    </section>
  );
}
