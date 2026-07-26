import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type DepthLevel, type OrderBook as OrderBookData } from "../lib/api";
import { fromUnits, scaleOf, toUnits, trimZeros, withThousands } from "../lib/amount";

type Row = {
  price: string;
  quantity: string;
  cumulative: string; // running total of quantity, from the best price outwards
  depth: number; // 0..100, for the background bar
};

/**
 * Build display rows from one side of the book.
 * `side` arrives best-price-first, so the cumulative total grows away from the spread —
 * which is exactly what a taker would eat through if they kept walking the book.
 */
function buildRows(side: DepthLevel[]): Row[] {
  if (side.length === 0) return [];
  const qScale = scaleOf(side[0].quantity);

  let running = 0n;
  const withTotals = side.map((e) => {
    running += toUnits(e.quantity, qScale);
    return { entry: e, cum: running };
  });

  const max = running; // the last cumulative is the largest
  return withTotals.map(({ entry, cum }) => ({
    price: entry.price,
    quantity: entry.quantity,
    cumulative: fromUnits(cum, qScale),
    // Number() only for a pixel width — never for money.
    depth: max > 0n ? Number((cum * 10000n) / max) / 100 : 0,
  }));
}

/** best ask − best bid, as a fixed-decimal string. Both sides arrive best-first. */
function spreadOf(book: OrderBookData | null): string | null {
  const ask = book?.asks[0]?.price;
  const bid = book?.bids[0]?.price;
  if (!ask || !bid) return null;
  const s = Math.max(scaleOf(ask), scaleOf(bid));
  return fromUnits(toUnits(ask, s) - toUnits(bid, s), s);
}

/** "BTC/USDT" -> "BTCUSDT": the form/page speak in pairs, the market API in symbols. */
function toSymbol(pair: string): string {
  return pair.replace("/", "").toUpperCase();
}

function priceText(p: string): string {
  return withThousands(trimZeros(p, 2));
}
function qtyText(q: string): string {
  return trimZeros(q, 5);
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
  /** Bump to force a reload (e.g. after an order is placed). */
  refreshToken = 0,
  /** Clicking a row sends its price to the order form — standard exchange UX. */
  onPriceClick,
}: {
  pair?: string;
  refreshToken?: number;
  onPriceClick?: (price: string) => void;
}) {
  const [book, setBook] = useState<OrderBookData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("both");

  const load = useCallback(async () => {
    setError("");
    try {
      setBook(await api.orderBook(toSymbol(pair)));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the order book");
    } finally {
      setLoading(false);
    }
  }, [pair]);

  // refreshToken belongs here, not in load's deps: it isn't read by the fetch, it just
  // signals "run it again".
  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  const bids = buildRows(book?.bids ?? []);
  // Asks come back best(lowest)-first. Displayed reversed so the best ask sits at the bottom,
  // right against the spread — the standard exchange layout.
  const asks = buildRows(book?.asks ?? []).reverse();
  const bestAsk = book?.asks[0]?.price ?? null;
  const spread = spreadOf(book);

  return (
    <div className="ob">
      <div className="ob-head">
        <h2>Order Book</h2>
        <span className="ob-pair">{book?.symbol ?? toSymbol(pair)}</span>
        <button className="ob-refresh" onClick={() => void load()} title="Reload">
          ⟳
        </button>
      </div>

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

      <div className="ob-cols">
        <span>Price (USDT)</span>
        <span className="r">Amount (BTC)</span>
        <span className="r">Total (BTC)</span>
      </div>

      {loading ? (
        <div className="ob-msg">Loading…</div>
      ) : error ? (
        <div className="ob-msg err">{error}</div>
      ) : (
        <>
          {view !== "bids" && (
          <div className="ob-side">
            {asks.length === 0 ? (
              <div className="ob-msg">No sell orders</div>
            ) : (
              asks.map((r) => (
                <div
                  className={`ob-row ask ${onPriceClick ? "clickable" : ""}`}
                  key={r.price}
                  onClick={() => onPriceClick?.(r.price)}
                >
                  <span className="ob-bar" style={{ width: `${r.depth}%` }} aria-hidden />
                  <span className="ob-price">{priceText(r.price)}</span>
                  <span className="ob-qty">{qtyText(r.quantity)}</span>
                  <span className="ob-cum">{qtyText(r.cumulative)}</span>
                </div>
              ))
            )}
          </div>
          )}

          {/* Kept visible in every view — the last price is the reference point for both sides. */}
          <div className="ob-spread">
            <span className="ob-last">{bestAsk ? priceText(bestAsk) : "—"}</span>
            <span className="ob-spread-label">
              Spread {spread ? priceText(spread) : "—"}
            </span>
          </div>

          {view !== "asks" && (
          <div className="ob-side">
            {bids.length === 0 ? (
              <div className="ob-msg">No buy orders</div>
            ) : (
              bids.map((r) => (
                <div
                  className={`ob-row bid ${onPriceClick ? "clickable" : ""}`}
                  key={r.price}
                  onClick={() => onPriceClick?.(r.price)}
                >
                  <span className="ob-bar" style={{ width: `${r.depth}%` }} aria-hidden />
                  <span className="ob-price">{priceText(r.price)}</span>
                  <span className="ob-qty">{qtyText(r.quantity)}</span>
                  <span className="ob-cum">{qtyText(r.cumulative)}</span>
                </div>
              ))
            )}
          </div>
          )}
        </>
      )}
    </div>
  );
}
