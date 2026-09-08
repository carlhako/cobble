/** A client-side filter field shown above a long list of settings or rules
 *  (web-ui-shell: "Long setting lists can be filtered by name"). It holds no
 *  state of its own — the section owns the query and the filtering. The
 *  matching predicate lives in ./filter. */

export interface FilterBarProps {
  value: string;
  onChange: (next: string) => void;
  /** How many rows are shown after filtering. */
  shown: number;
  /** How many rows there are in total. */
  total: number;
  /** Placeholder / accessible name, e.g. "Filter settings". */
  label: string;
}

export function FilterBar({ value, onChange, shown, total, label }: FilterBarProps) {
  return (
    <div className="filter-bar">
      <input
        type="search"
        className="filter-input"
        aria-label={label}
        placeholder={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className="filter-count" aria-live="polite">
        {value.trim() === "" ? `${total} shown` : `${shown} of ${total} shown`}
      </span>
    </div>
  );
}
