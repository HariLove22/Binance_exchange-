import { useEffect, useMemo, useState } from "react";
import { api, type UniverseRow } from "../lib/api";
import { useTickers } from "../lib/useLive";
import "./markets.css";

/**
 * Markets overview — a Binance-style board: highlight cards (top gainer / loser / volume), a quote
 * filter, search, and a live-priced token table. Data comes from our universe endpoint (the full
 * Binance instrument set); the visible rows tick live over the shared feed. Clicking a row opens it
 * in the trading terminal.
 */
export function Markets({ onPick }: { onPick: (symbol: string) => void }) {
  const [rows, setRows] = useState<UniverseRow[]>([]);
  const [segments, setSegments] = useState<string[]>([]);
  const [quote, setQuote] = useState("USDT");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.marketUniverse(quote, search || undefined)
      .then((u) => { setRows(u.markets); if (u.segments.length) setSegments(u.segments); })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [quote, search]);

  // Live-tick the rows currently shown (cap to keep the socket sane).
  const shown = rows.slice(0, 100);
  const live = useTickers(shown.map((r) => r.symbol));
  const withLive = shown.map((r) => {
    const t = live[r.symbol];
    return t ? { ...r, price: t.price, change_percent: t.changePercent, quote_volume: t.quoteVolume } : r;
  });

  const gainers = useMemo(() => [...rows].sort((a, b) => b.change_percent - a.change_percent).slice(0, 3), [rows]);
  const losers = useMemo(() => [...rows].sort((a, b) => a.change_percent - b.change_percent).slice(0, 3), [rows]);
  const volume = useMemo(() => [...rows].sort((a, b) => b.quote_volume - a.quote_volume).slice(0, 3), [rows]);

  return (
    <div className="mkt">
      <div className="mkt-head">
        <h1>Markets</h1>
        <p className="mkt-sub">Live prices across the full instrument set. Click a pair to trade.</p>
      </div>

      <div className="mkt-cards">
        <HighlightCard title="Top Gainers" rows={gainers} onPick={onPick} />
        <HighlightCard title="Top Losers" rows={losers} onPick={onPick} />
        <HighlightCard title="Top Volume" rows={volume} onPick={onPick} volume />
      </div>

      <div className="mkt-toolbar">
        <div className="mkt-segs">
          {["USDT", ...segments.filter((s) => s !== "USDT")].slice(0, 9).map((s) => (
            <button key={s} className={quote === s ? "on" : ""} onClick={() => setQuote(s)}>{s}</button>
          ))}
        </div>
        <input className="mkt-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search coin" />
      </div>

      <div className="mkt-table">
        <div className="mkt-h">
          <span>Name</span>
          <span className="num">Price</span>
          <span className="num">24h Change</span>
          <span className="num">24h Volume</span>
          <span className="num">Action</span>
        </div>
        {loading && <p className="mkt-empty">loading markets…</p>}
        {!loading && withLive.length === 0 && <p className="mkt-empty">No pairs for {quote}{search ? ` matching “${search}”` : ""}.</p>}
        {withLive.map((r) => {
          const up = r.change_percent >= 0;
          return (
            <button className="mkt-row" key={r.symbol} onClick={() => r.tradeable && onPick(r.symbol)}>
              <span className="mkt-name">
                <span className="mkt-coin">{r.base}</span><span className="mkt-quote">/{r.quote}</span>
                {!r.tradeable && <span className="mkt-viewonly">view</span>}
              </span>
              <span className="num mono">{fmtPrice(r.price)}</span>
              <span className={`num ${up ? "up" : "down"}`}>{up ? "+" : ""}{r.change_percent.toFixed(2)}%</span>
              <span className="num mono dim">{fmtVol(r.quote_volume)}</span>
              <span className="num">
                <span className={`mkt-trade ${r.tradeable ? "" : "off"}`}>{r.tradeable ? "Trade" : "—"}</span>
              </span>
            </button>
          );
        })}
        {!loading && rows.length > shown.length && (
          <p className="mkt-more">Showing top {shown.length} of {rows.length} — refine with search.</p>
        )}
      </div>
    </div>
  );
}

function HighlightCard({ title, rows, onPick, volume }: { title: string; rows: UniverseRow[]; onPick: (s: string) => void; volume?: boolean }) {
  return (
    <div className="mkt-card">
      <div className="mkt-card-h">{title}</div>
      {rows.map((r) => {
        const up = r.change_percent >= 0;
        return (
          <button className="mkt-card-row" key={r.symbol} onClick={() => r.tradeable && onPick(r.symbol)}>
            <span className="mkt-card-name">{r.base}<em>/{r.quote}</em></span>
            <span className="mono">{fmtPrice(r.price)}</span>
            <span className={volume ? "dim mono" : up ? "up" : "down"}>
              {volume ? fmtVol(r.quote_volume) : `${up ? "+" : ""}${r.change_percent.toFixed(2)}%`}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function fmtPrice(p: number): string {
  if (!p) return "—";
  if (p >= 1000) return p.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(2);
  if (p >= 0.01) return p.toFixed(4);
  return p.toPrecision(4);
}

function fmtVol(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}
