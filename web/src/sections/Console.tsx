import { useEffect, useRef, useState } from "react";
import { useConsole } from "../api/useConsole";
import { useStatus } from "../api/StatusContext";
import { ApiCallError } from "../api/client";

export function Console() {
  const { lines, connected, send } = useConsole();
  const { status } = useStatus();
  const running = status?.run_state === "running";

  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);

  useEffect(() => {
    const el = logRef.current;
    if (el && pinnedToBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  function onScroll() {
    const el = logRef.current;
    if (!el) return;
    pinnedToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const command = draft.trim();
    if (!command || !running) return;
    setError(null);
    try {
      await send(command);
      setDraft("");
    } catch (err) {
      setError(err instanceof ApiCallError ? err.message : String(err));
    }
  }

  return (
    <section className="section console">
      <h1>
        Console
        {!connected && <span className="badge badge-warn">disconnected</span>}
      </h1>

      <div className="console-log" ref={logRef} onScroll={onScroll}>
        {lines.map((l) => (
          <div key={l.seq} className={`cl cl-${l.kind}`}>
            {l.kind === "command" ? `> ${l.text}` : l.text}
          </div>
        ))}
        {lines.length === 0 && <div className="muted">No output yet.</div>}
      </div>

      <form className="console-input" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={running ? "Type a command, e.g. list" : "Server is not running"}
          disabled={!running}
          aria-label="console command"
        />
        <button type="submit" disabled={!running || draft.trim() === ""}>
          Send
        </button>
      </form>
      {error && (
        <div className="controls-error" role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
