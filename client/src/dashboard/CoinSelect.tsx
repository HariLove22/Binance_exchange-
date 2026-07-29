import { useEffect, useRef, useState } from "react";
import { CoinIcon } from "./CoinIcon";

/**
 * A coin picker with icons and search — the icon-pill dropdown a real exchange uses, replacing a
 * bare <select> (which can't render images).
 *
 * `tradeable` (optional) marks the coins the platform actually custodies. The others still show —
 * so the list looks like a full exchange — but are flagged, because buy/convert only works for
 * coins in our ledger.
 */
export function CoinSelect({
  value,
  options,
  onChange,
  tradeable,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  tradeable?: Set<string>;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  // Close on any click outside the widget.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const filtered = query ? options.filter((s) => s.includes(query.toUpperCase())) : options;

  return (
    <div className="coin-select" ref={ref}>
      <button
        type="button"
        className="coin-select-btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <CoinIcon symbol={value} size={20} />
        <span className="coin-select-sym">{value}</span>
        <span className="coin-select-chev">▾</span>
      </button>

      {open && (
        <div className="coin-select-pop" role="listbox">
          <input
            autoFocus
            className="coin-select-search"
            placeholder="Search coin"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="coin-select-list">
            {filtered.length === 0 ? (
              <div className="coin-select-empty">No coin found</div>
            ) : (
              filtered.map((s) => (
                <button
                  type="button"
                  key={s}
                  role="option"
                  aria-selected={s === value}
                  className={`coin-select-opt ${s === value ? "on" : ""}`}
                  onClick={() => {
                    onChange(s);
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  <CoinIcon symbol={s} size={22} />
                  <span className="coin-select-opt-sym">{s}</span>
                  {tradeable && !tradeable.has(s) && (
                    <span className="coin-select-tag" title="View only — not custodied for buy/convert yet">
                      chart only
                    </span>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
