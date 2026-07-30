import { useEffect, useRef, useState } from "react";
import { api, type DepthLevel, type OrderBook as OrderBookData, type TradeTick } from "../lib/api";
import { useMarketWs } from "../lib/marketWs";
import { fromUnits, scaleOf, toUnits, trimZeros, withThousands } from "../lib/amount";

type Row = {
  price: string;
  quantity: string;
  cumBase: string; // running total of quantity, from the best price outwards
  cumQuote: string; // running total of price*quantity (spend to sweep to here)
  depth: number; // 0..100, for the background bar
  mine: boolean; // a resting order of the user's sits at this level
};

/** Max decimal places seen across the strings, floored at `min`, capped at 8. */
function decimalsOf(vals: string[], min: number): number {
  let d = min;
  for (const v of vals) d = Math.max(d, scaleOf(v));
  return Math.min(d, 8);
}

/**
 * Aggregate raw levels into price buckets of `gf` ticks. Bids floor to the bucket, asks ceil —
 * so grouping never visually swallows the spread. gf===1n means no grouping.
 */
function groupLevels(levels: DepthLevel[], S: number, qScale: number, gf: bigint, ceil: boolean): DepthLevel[] {
  if (gf === 1n || levels.length === 0) return levels;
  const buckets = new Map<string, bigint>();
  for (const l of levels) {
    const u = toUnits(l.price, S);
    let b = (u / gf) * gf;
    if (ceil && u % gf !== 0n) b += gf;
    const key = fromUnits(b, S);
    buckets.set(key, (buckets.get(key) ?? 0n) + toUnits(l.quantity, qScale));
  }
  const out = [...buckets.entries()].map(([price, q]) => ({ price, quantity: fromUnits(q, qScale) }));
  out.sort((a, b) => (toUnits(a.price, S) < toUnits(b.price, S) ? 1 : -1) * (ceil ? -1 : 1));
  return out;
}

/**
 * Build display rows from one side of the book.
 * `side` arrives best-price-first, so the cumulative total grows away from the spread —
 * which is exactly what a taker would eat through if they kept walking the book.
 */
function buildRows(side: DepthLevel[], S: number, qScale: number, mine: Set<string>): Row[] {
  if (side.length === 0) return [];
  let base = 0n;
  let quote = 0n; // scale S + qScale
  const rows = side.map((e) => {
    const q = toUnits(e.quantity, qScale);
    base += q;
    quote += toUnits(e.price, S) * q;
    return {
      price: e.price,
      quantity: e.quantity,
      cumBase: fromUnits(base, qScale),
      cumQuote: fromUnits(quote, S + qScale),
      base,
      mine: mine.has(e.price),
    };
  });
  const max = base;
  return rows.map((r) => ({
    price: r.price,
    quantity: r.quantity,
    cumBase: r.cumBase,
    cumQuote: r.cumQuote,
    mine: r.mine,
    // Number() only for a pixel width — never for money.
    depth: max > 0n ? Number((r.base * 10000n) / max) / 100 : 0,
  }));
}

/** best ask − best bid, as a fixed-decimal string. Both sides arrive best-first. */
function spreadOf(book: OrderBookData | null, S: number): string | null {
  const ask = book?.asks[0]?.price;
  const bid = book?.bids[0]?.price;
  if (!ask || !bid) return null;
  return fromUnits(toUnits(ask, S) - toUnits(bid, S), S);
}

/** "BTC/USDT" -> "BTCUSDT": the form/page speak in pairs, the market API in symbols. */
function toSymbol(pair: string): string {
  return pair.replace("/", "").toUpperCase();
}

/** Which side(s) of the book to show. */
type View = "both" | "bids" | "asks";

const RED = "#f6465d";
const GREEN = "#0ecb81";

/** Small stacked-bars glyph: two rows tinted for the ask side, two for the bid side. */
function DepthGlyph({ top, bottom }: { top: string; bottom: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
      <rect x="0" y="0" width="14" height="2.4" rx="1" fill={top} />
      <rect x="0" y="3.7" width="9" height="2.4" rx="1" fill={top} />
      <rect x="0" y="7.6" width="14" height="2.4" rx="1" fill={bottom} />
      <rect x="0" y="11.3" width="9" height="2.4" rx="1" fill={bottom} />
    </svg>
  );
}

const VIEWS: { key: View; label: string; top: string; bottom: string }[] = [
  { key: "both", label: "Both sides", top: RED, bottom: GREEN },
  { key: "bids", label: "Buy orders", top: GREEN, bottom: GREEN },
  { key: "asks", label: "Sell orders", top: RED, bottom: RED },
];

export function OrderBook({
  pair = "BTC/USDT",
  /** False for a coin with no market here — there is no book to subscribe to. */
  tradeable = true,
  /** Bump to refetch the user's open orders (after placing/cancelling) for the "mine" markers. */
  refreshToken = 0,
  /** Clicking a row sends its price to the order form — standard exchange UX. */
  onPriceClick,
}: {
  pair?: string;
  tradeable?: boolean;
  refreshToken?: number;
  onPriceClick?: (price: string) => void;
}) {
  const [base, quote] = pair.split("/");
  const sym = toSymbol(pair);
  const [view, setView] = useState<View>("both");
  const [group, setGroup] = useState(1); // tick multiplier: 1, 10, 100, 1000
  const [cumQuote, setCumQuote] = useState(false); // Total column in quote (USDT) instead of base

  const { book, trades, live } = useMarketWs(tradeable ? sym : null);
  const loading = book === null;

  // The user's own resting orders on this market — to mark their price levels in the book.
  const [myPrices, setMyPrices] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!tradeable) return;
    let alive = true;
    api
      .openOrders()
      .then((os) => alive && setMyPrices(new Set(os.filter((o) => o.symbol === sym && o.price).map((o) => o.price as string))))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [sym, tradeable, refreshToken]);

  // Precision from the data itself (backend strips trailing zeros, so max scale = the tick in use).
  const priceDecimals = decimalsOf([...(book?.bids ?? []), ...(book?.asks ?? [])].map((l) => l.price), 2);
  const qtyDecimals = decimalsOf([...(book?.bids ?? []), ...(book?.asks ?? [])].map((l) => l.quantity), 2);
  const S = priceDecimals;
  const gf = BigInt(group);

  const priceText = (p: string) => withThousands(trimZeros(p, priceDecimals));
  const qtyText = (q: string) => trimZeros(q, qtyDecimals);

  // Bucket the user's prices the same way the book is grouped, so a marker lands on its level.
  const myBuckets = new Set(
    [...myPrices].map((p) => {
      if (gf === 1n) return p;
      const u = toUnits(p, S);
      return fromUnits((u / gf) * gf, S);
    }),
  );

  const rawBids = groupLevels(book?.bids ?? [], S, qtyDecimals, gf, false);
  const rawAsks = groupLevels(book?.asks ?? [], S, qtyDecimals, gf, true);
  const bids = buildRows(rawBids, S, qtyDecimals, myBuckets);
  // Asks come back best(lowest)-first. Displayed reversed so the best ask sits at the bottom,
  // right against the spread — the standard exchange layout.
  const asks = buildRows(rawAsks, S, qtyDecimals, myBuckets).reverse();

  const spread = spreadOf(book, S);
  const spreadPct = spread && book?.asks[0] ? (Number(spread) / Number(book.asks[0].price)) * 100 : null;

  // Last traded price + tick direction (green up / red down), the centrepiece of a real book.
  const last = trades[0]?.price ?? null;
  const lastDir = trades[0] && trades[1] ? Math.sign(Number(trades[0].price) - Number(trades[1].price)) : 0;

  // Buy/sell pressure: share of visible depth on each side.
  const bidVol = bids.length ? Number(bids[bids.length - 1].cumBase) : 0;
  const askVol = asks.length ? Number(asks[0].cumBase) : 0;
  const bidPct = bidVol + askVol > 0 ? (bidVol / (bidVol + askVol)) * 100 : 50;

  const asksRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = asksRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [asks]);

  const cell = (r: Row) => (
    <>
      <span className="ob-bar" style={{ width: `${r.depth}%` }} aria-hidden />
      {r.mine && <span className="ob-mine" title="Your order rests here" aria-hidden />}
      <span className="ob-price">{priceText(r.price)}</span>
      <span className="ob-qty">{qtyText(r.quantity)}</span>
      <span className="ob-cum">{cumQuote ? withThousands(trimZeros(r.cumQuote, 2)) : qtyText(r.cumBase)}</span>
    </>
  );
  const rowTitle = (r: Row) =>
    `Sum ${qtyText(r.cumBase)} ${base} · ${withThousands(trimZeros(r.cumQuote, 2))} ${quote} · avg ${withThousands((Number(r.cumQuote) / Number(r.cumBase)).toFixed(2))}`;

  return (
    <div className="ob">
      <div className="ob-head">
        <h2>Order Book</h2>
        <span className="ob-pair">{book?.symbol ?? sym}</span>
        {tradeable ? (
          <span className={`ob-live ${live ? "on" : ""}`} title={live ? "Live — updates automatically" : "Reconnecting…"}>
            <span className="ob-live-dot" />
            {live ? "Live" : "…"}
          </span>
        ) : (
          <span className="ob-live">view only</span>
        )}
      </div>

      <div className="ob-controls">
        <div className="ob-filter">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              className={`ob-filter-btn ${view === v.key ? "on" : ""}`}
              onClick={() => setView(v.key)}
              data-tip={v.label}
              aria-label={v.label}
              aria-pressed={view === v.key}
            >
              <DepthGlyph top={v.top} bottom={v.bottom} />
            </button>
          ))}
        </div>
        <select className="ob-group" value={group} onChange={(e) => setGroup(Number(e.target.value))} title="Price grouping">
          {[1, 10, 100, 1000].map((g) => (
            <option key={g} value={g}>
              {trimZeros(fromUnits(BigInt(g), S), priceDecimals)}
            </option>
          ))}
        </select>
      </div>

      <div className="ob-cols">
        <span>Price ({quote})</span>
        <span className="r">Amount ({base})</span>
        <button type="button" className="ob-cum-toggle r" onClick={() => setCumQuote((q) => !q)} title="Toggle base / quote">
          Total ({cumQuote ? quote : base})
        </button>
      </div>

      {!tradeable ? (
        <div className="ob-msg">No market here yet — {base} is view-only.</div>
      ) : loading ? (
        <div className="ob-msg">Connecting…</div>
      ) : (
        <>
          {view !== "bids" && (
            <div className="ob-side ob-side-asks" ref={asksRef}>
              {asks.length === 0 ? (
                <div className="ob-msg">No sell orders</div>
              ) : (
                asks.map((r) => (
                  <div className={`ob-row ask ${r.mine ? "mine" : ""} ${onPriceClick ? "clickable" : ""}`} key={r.price} title={rowTitle(r)} onClick={() => onPriceClick?.(r.price)}>
                    {cell(r)}
                  </div>
                ))
              )}
            </div>
          )}

          {/* Last traded price, coloured by tick direction — the reference point for both sides. */}
          <div className="ob-spread">
            <span className={`ob-last ${lastDir > 0 ? "up" : lastDir < 0 ? "down" : ""}`}>
              {last ? priceText(last) : "—"}
              {lastDir !== 0 && <span className="ob-last-arrow">{lastDir > 0 ? "↑" : "↓"}</span>}
            </span>
            <span className="ob-spread-label">
              Spread {spread ? priceText(spread) : "—"}
              {spreadPct !== null && ` (${spreadPct.toFixed(2)}%)`}
            </span>
          </div>

          {view !== "asks" && (
            <div className="ob-side ob-side-bids">
              {bids.length === 0 ? (
                <div className="ob-msg">No buy orders</div>
              ) : (
                bids.map((r) => (
                  <div className={`ob-row bid ${r.mine ? "mine" : ""} ${onPriceClick ? "clickable" : ""}`} key={r.price} title={rowTitle(r)} onClick={() => onPriceClick?.(r.price)}>
                    {cell(r)}
                  </div>
                ))
              )}
            </div>
          )}

          {/* Buy vs sell pressure across the visible book. */}
          <div className="ob-ratio" title={`Buy ${bidPct.toFixed(0)}% · Sell ${(100 - bidPct).toFixed(0)}%`}>
            <span className="ob-ratio-buy" style={{ width: `${bidPct}%` }}>B {bidPct.toFixed(0)}%</span>
            <span className="ob-ratio-sell" style={{ width: `${100 - bidPct}%` }}>{(100 - bidPct).toFixed(0)}% S</span>
          </div>
        </>
      )}

      {tradeable && (
        <div className="ob-trades">
          <div className="ob-trades-head">Recent Trades</div>
          <div className="ob-cols">
            <span>Price ({quote})</span>
            <span className="r">Amount ({base})</span>
            <span className="r">Time</span>
          </div>
          {trades.length === 0 ? (
            <div className="ob-msg">No trades yet</div>
          ) : (
            <div className="ob-trades-list">
              {trades.slice(0, 30).map((t: TradeTick) => (
                <div className={`ob-trade ${t.taker_side === "BUY" ? "up" : "down"}`} key={t.id}>
                  <span className="ob-price">{priceText(t.price)}</span>
                  <span className="ob-qty">{qtyText(t.quantity)}</span>
                  <span className="ob-time">{new Date(t.created_at).toLocaleTimeString()}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
