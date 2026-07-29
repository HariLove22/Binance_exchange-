import { useEffect, useRef, useState } from "react";
import { findFiat, searchFiat } from "../lib/fiat";

/**
 * A fiat currency picker with flags and search, over the static ISO 4217 list in `lib/fiat`.
 * Mirrors CoinSelect's icon-pill dropdown so the "You pay" and "You receive" controls match,
 * and replaces a bare <select> (which can't render a flag or filter by name).
 *
 * `supported` (optional) marks the currencies the on-ramp actually has a rate for. The rest
 * still show — the list is meant to look complete — but are flagged, because a buy only quotes
 * for currencies the backend prices.
 */
export function FiatSelect({
  value,
  onChange,
  supported,
}: {
  value: string;
  onChange: (v: string) => void;
  supported?: Set<string>;
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

  const selected = findFiat(value);
  const filtered = searchFiat(query);

  return (
    <div className="coin-select fiat-select" ref={ref}>
      <button
        type="button"
        className="coin-select-btn"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="fiat-flag" aria-hidden>{selected?.flag ?? "🏳️"}</span>
        <span className="coin-select-sym">{value}</span>
        <span className="coin-select-chev">▾</span>
      </button>

      {open && (
        <div className="coin-select-pop" role="listbox">
          <input
            autoFocus
            className="coin-select-search"
            placeholder="Search currency"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="coin-select-list">
            {filtered.length === 0 ? (
              <div className="coin-select-empty">No currency found</div>
            ) : (
              filtered.map((c) => (
                <button
                  type="button"
                  key={c.code}
                  role="option"
                  aria-selected={c.code === value}
                  className={`coin-select-opt ${c.code === value ? "on" : ""}`}
                  onClick={() => {
                    onChange(c.code);
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  <span className="fiat-flag" aria-hidden>{c.flag}</span>
                  <span className="coin-select-opt-sym">{c.code}</span>
                  <span className="fiat-name">{c.name}</span>
                  {supported && !supported.has(c.code) && (
                    <span className="coin-select-tag" title="No live rate yet — buying isn't available for this currency">
                      no rate
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
