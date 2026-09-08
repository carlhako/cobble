/** Shared predicate for the client-side filter fields on the Configuration and
 *  Gamerules sections (web-ui-shell: "Long setting lists can be filtered by
 *  name"). Kept apart from FilterBar.tsx so that file exports only a component. */

/** True when every whitespace-separated term in `query` is a case-insensitive
 *  substring of at least one of `fields`. An empty query matches everything. */
export function matchesFilter(
  query: string,
  ...fields: (string | null | undefined)[]
): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const hay = fields.filter(Boolean).join(" ").toLowerCase();
  return terms.every((t) => hay.includes(t));
}
