import type { ValidationIssue } from "../api/client";

/** Settings that are each valid but conflict with one another, reported by every
 *  configuration read and write. Shown at the top of the Configuration and
 *  Network sections; it clears on the re-read after a save that resolves it. */
export function ConflictBanner({ conflicts }: { conflicts: ValidationIssue[] }) {
  if (conflicts.length === 0) return null;
  return (
    <div className="panel is-warn" role="alert" aria-label="configuration conflicts">
      <strong>
        {conflicts.length === 1
          ? "Two settings conflict"
          : `${conflicts.length} setting conflicts`}
      </strong>
      {conflicts.map((c) => (
        <p key={`${c.key}:${c.message}`}>{c.message}</p>
      ))}
    </div>
  );
}
