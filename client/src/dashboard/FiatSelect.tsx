import { useEffect, useRef, useState } from "react";
import { FIAT_CURRENCIES, type FiatCurrency } from "../lib/fiat";

/**
 * A currency picker with flags and search. Defaults to the static ISO 4217 list in `lib/fiat`,
 * but accepts a custom `items` list so a caller can prepend the market's native quote (e.g. USDT)
 * ahead of the fiats. Mirrors CoinSelect's icon-pill dropdown so the pay/receive controls match,
 * and replaces a bare <select> (which can't render a flag or filter by name).
 *
 * `supported` (optional) marks the currencies a caller can actually act on. The rest still show —
 * the list is meant to look complete — but are flagged.
 */
export function FiatSelect({
  value,
  onChange,
  items = FIAT_CURRENCIES,
  supported,
}: {
  value: string;
  onChange: (v: string) => void;
  items?: FiatCurrency[];
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

  const selected = items.find((c) => c.code === value);
  const q = query.trim().toLowerCase();
  const filtered = q
    ? items.filter((c) => c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q))
    : items;

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
