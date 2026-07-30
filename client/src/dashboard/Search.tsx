import { useEffect, useMemo, useRef, useState } from "react";
import { api, type UniverseRow } from "../lib/api";
import { useTickers } from "../lib/useLive";
import { navigate } from "../router";
import { ISearch } from "./icons";
import "./search.css";

/**
 * Top-bar search: a dropdown with a live coin search and a trending list, like Binance's. Opens from
 * the magnifier, closes on outside click / Escape. Picking a coin opens it in the trading terminal.
 */
export function Search() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<UniverseRow[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open && rows.length === 0) api.marketUniverse("USDT").then((u) => setRows(u.markets)).catch(() => {});
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open, rows.length]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, []);

  const trending = useMemo(() => [...rows].sort((a, b) => b.quote_volume - a.quote_volume).slice(0, 6), [rows]);
  const results = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return [];
    return rows.filter((r) => r.base.includes(q) || r.symbol.includes(q)).slice(0, 20);
  }, [rows, query]);

  const shown = query.trim() ? results : trending;
  const live = useTickers(shown.map((r) => r.symbol));

  function pick(r: UniverseRow) {
    if (!r.tradeable) return;
    sessionStorage.setItem("trade_symbol", r.symbol);
    navigate("/dashboard/trade");
    setOpen(false);
    setQuery("");
  }

  return (
    <div className="search-wrap" ref={ref}>
      <button className="icon-btn" aria-label="Search" onClick={() => setOpen((o) => !o)}><ISearch /></button>
      {open && (
        <div className="search-panel">
          <div className="search-box">
            <ISearch />
            <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search coin, e.g. BTC" />
            {query && <button className="search-clear" onClick={() => setQuery("")}>✕</button>}
          </div>

          <div className="search-section-title">{query.trim() ? "Results" : "🔥 Trending"}</div>
          <div className="search-list">
            {shown.length === 0 && <p className="search-empty">{query.trim() ? "No coins match." : "loading…"}</p>}
            {shown.map((r, i) => {
              const t = live[r.symbol];
              const price = t?.price ?? r.price;
              const chg = t?.changePercent ?? r.change_percent;
              const up = chg >= 0;
              return (
                <button className="search-row" key={r.symbol} onClick={() => pick(r)} disabled={!r.tradeable}>
                  {!query.trim() && <span className="search-rank">{i + 1}</span>}
                  <span className="search-coin">{r.base}<em>/{r.quote}</em>{!r.tradeable && <span className="search-vo">view</span>}</span>
                  <span className="search-price mono">{fmt(price)}</span>
                  <span className={`search-chg ${up ? "up" : "down"}`}>{up ? "+" : ""}{chg.toFixed(2)}%</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function fmt(p: number): string {
  if (!p) return "—";
  if (p >= 1000) return "$" + p.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (p >= 1) return "$" + p.toFixed(2);
  if (p >= 0.01) return "$" + p.toFixed(4);
  return "$" + p.toPrecision(4);
}
