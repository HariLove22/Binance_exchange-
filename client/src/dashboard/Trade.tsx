import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  trimAmount,
  type Balance,
  type MarketInfo,
  type OrderBook,
  type OrderRow,
  type TradeTick,
  type UniverseRow,
} from "../lib/api";
import { useTicker } from "../lib/useLive";
import { TradeChart } from "./TradeChart";
import "./trade.css";

const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"];

/**
 * Spot trading terminal, laid out like Binance: order book and our trades on the left, the chart
 * and open orders in the centre, the order form on the right.
 *
 * Nobody types a price by hand. For a market order there is no price field at all — it fills at
 * the live best bid/ask. For a limit order the price is pre-filled with the live price and a click
 * on any order-book row sets it. Amount comes from a slider over the account's available balance.
 * That is how a real terminal works, and what makes "trade from the selected account" concrete:
 * the form only ever offers what the account actually holds.
 */
export function Trade() {
  const [markets, setMarkets] = useState<MarketInfo[]>([]);
  const [symbol, setSymbol] = useState("ETHUSDT");
  const [interval, setInterval] = useState("1m");
  const [balances, setBalances] = useState<Balance[]>([]);
  const [clickedPrice, setClickedPrice] = useState<string | null>(null);

  const loadBalances = useCallback(() => {
    api.balances().then(setBalances).catch(() => setBalances([]));
  }, []);

  useEffect(() => {
    api.marketSymbols().then((m) => {
      setMarkets(m);
      if (m.length && !m.find((x) => x.symbol === "ETHUSDT")) setSymbol(m[0].symbol);
    }).catch(() => {});
    loadBalances();
  }, [loadBalances]);

  useEffect(() => {
    const h = () => loadBalances();
    window.addEventListener("orders-changed", h);
    return () => window.removeEventListener("orders-changed", h);
  }, [loadBalances]);

  const market = markets.find((m) => m.symbol === symbol);
  const tradeable = market !== undefined; // only pairs we run a market for can be traded here
  const ticker = useTicker(symbol);
  const up = (ticker?.changePercent ?? 0) >= 0;

  return (
    <div className="trade">
      <div className="term-grid">
        {/* ── ticker bar (full width) ── */}
        <div className="g-ticker tk-bar">
          <div className="tk-symbol">
            <span className="tk-name">{symbol.replace(/USDT$/, "")}<span className="tk-quote">/USDT</span></span>
            {!tradeable && <span className="tk-viewonly">view only</span>}
          </div>
          {ticker ? (
            <>
              <span className={`tk-price ${up ? "bid" : "ask"}`}>{fmtPx(ticker.price)}</span>
              <div className="tk-stats">
                <span className={`tk-chg ${up ? "bid" : "ask"}`}>{up ? "+" : ""}{ticker.changePercent.toFixed(2)}%</span>
                <span className="tk-s"><i>24h High</i>{fmtPx(ticker.high)}</span>
                <span className="tk-s"><i>24h Low</i>{fmtPx(ticker.low)}</span>
                <span className="tk-s"><i>24h Vol</i>{(ticker.quoteVolume / 1e6).toFixed(1)}M</span>
                <span className="tk-live">● live</span>
              </div>
            </>
          ) : (
            <span className="tk-loading">connecting to live feed…</span>
          )}
          <div className="tk-spacer" />
          <SeedLiquidity />
        </div>

        {/* ── left: order book + our trades ── */}
        <aside className="g-left">
          {tradeable ? (
            <>
              <OrderBookPanel symbol={symbol} onPick={setClickedPrice} live={ticker?.price ?? null} />
              <RecentTrades symbol={symbol} />
            </>
          ) : (
            <div className="tp fill">
              <div className="tp-head"><span className="tp-title">Order book</span></div>
              <p className="tp-empty">Not traded on this exchange — view only.</p>
            </div>
          )}
        </aside>

        {/* ── center top: chart ── */}
        <section className="g-chart tp">
          <div className="tp-head">
            <span className="tp-title">{symbol}</span>
            <div className="ivals">
              {INTERVALS.map((i) => (
                <button key={i} className={interval === i ? "on" : ""} onClick={() => setInterval(i)}>{i}</button>
              ))}
            </div>
          </div>
          <TradeChart symbol={symbol} interval={interval} />
        </section>

        {/* ── center bottom: order form ── */}
        <section className="g-form tp">
          {tradeable ? (
            <OrderForm
              market={market}
              symbol={symbol}
              balances={balances}
              livePrice={ticker?.price ?? null}
              clickedPrice={clickedPrice}
            />
          ) : (
            <div className="viewonly-form">
              <p>Order entry is available only for pairs listed on this exchange.</p>
              <p className="viewonly-sub">The chart and price above are live from the reference feed.</p>
            </div>
          )}
        </section>

        {/* ── right: full market universe ── */}
        <aside className="g-market">
          <MarketList current={symbol} onPick={setSymbol} />
        </aside>

        {/* ── bottom: open orders (full width) ── */}
        <section className="g-orders tp">
          {tradeable ? <OpenOrders symbol={symbol} /> : (
            <>
              <div className="tp-head"><span className="tp-title">Open orders</span></div>
              <p className="tp-empty">—</p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- market list */

function fmtPx(p: number): string {
  if (p >= 1000) return p.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (p >= 1) return p.toFixed(2);
  if (p >= 0.01) return p.toFixed(4);
  return p.toPrecision(4);
}

/**
 * The full Binance market universe, all segments, from /market/all. Pairs we list for trading are
 * highlighted and come first; the rest are view-only. Prices refresh on a short poll (the whole
 * universe is thousands of rows — too many for individual WebSocket subscriptions, so the snapshot
 * is polled and the *selected* pair alone gets the live WS ticker in the header).
 */
function MarketList({ current, onPick }: { current: string; onPick: (s: string) => void }) {
  const [segments, setSegments] = useState<string[]>(["USDT"]);
  const [seg, setSeg] = useState("USDT");
  const [rows, setRows] = useState<UniverseRow[]>([]);
  const [q, setQ] = useState("");

  const load = useCallback(() => {
    api.marketUniverse(q ? undefined : seg, q || undefined)
      .then((u) => { setRows(u.markets); if (u.segments.length) setSegments(u.segments); })
      .catch(() => setRows([]));
  }, [seg, q]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 6000); // refresh prices
    return () => window.clearInterval(id);
  }, [load]);

  return (
    <div className="tp mkt-box">
      <div className="mkt-search">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search all markets" />
      </div>
      <div className="mkt-tabs">
        {segments.map((s) => (
          <span key={s} className={!q && seg === s ? "on" : ""} onClick={() => { setQ(""); setSeg(s); }}>{s}</span>
        ))}
      </div>
      <div className="mkt-cols"><span>Pair</span><span className="num">Price</span><span className="num">24h</span></div>
      <div className="mkt-list">
        {rows.length === 0 && <p className="tp-empty">loading markets…</p>}
        {rows.map((m) => {
          const up = m.change_percent >= 0;
          return (
            <button
              key={m.symbol}
              className={`mkt-row ${m.symbol === current ? "on" : ""} ${m.tradeable ? "tradeable" : ""}`}
              onClick={() => onPick(m.symbol)}
              title={m.tradeable ? "Tradeable here" : "View only — not listed for trading"}
            >
              <span className="mkt-name">
                {m.tradeable && <span className="mkt-dot" />}
                {m.base}<span className="mkt-quote">/{m.quote}</span>
              </span>
              <span className="num mono">{fmtPx(m.price)}</span>
              <span className={`num ${up ? "bid" : "ask"}`}>{up ? "+" : ""}{m.change_percent.toFixed(2)}%</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function SeedLiquidity() {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="seed-btn"
      disabled={busy}
      title="Dev: fund the market maker and re-quote around the live price"
      onClick={async () => {
        setBusy(true);
        try { await api.refreshMarketMaker(); } catch { /* ignore */ }
        finally { setBusy(false); window.dispatchEvent(new CustomEvent("book-changed")); }
      }}
    >
      {busy ? "seeding…" : "Seed liquidity"}
    </button>
  );
}

/* ---------------------------------------------------------------- poll hook */

function usePoll(fn: () => void, ms: number) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    saved.current();
    const id = window.setInterval(() => saved.current(), ms);
    const onChange = () => saved.current();
    window.addEventListener("book-changed", onChange);
    return () => { window.clearInterval(id); window.removeEventListener("book-changed", onChange); };
  }, [ms]);
}

/* ------------------------------------------------------------------- book */

function OrderBookPanel({
  symbol, onPick, live,
}: {
  symbol: string;
  onPick: (price: string) => void;
  live: number | null;
}) {
  const [book, setBook] = useState<OrderBook | null>(null);
  usePoll(() => { api.orderBook(symbol).then(setBook).catch(() => setBook(null)); }, 1500);

  const maxTotal = Math.max(
    ...(book?.asks ?? []).map((_, i, arr) => arr.slice(0, i + 1).reduce((s, l) => s + Number(l.quantity), 0)),
    ...(book?.bids ?? []).map((_, i, arr) => arr.slice(0, i + 1).reduce((s, l) => s + Number(l.quantity), 0)),
    1,
  );
  const cum = (arr: { quantity: string }[], i: number) => arr.slice(0, i + 1).reduce((s, l) => s + Number(l.quantity), 0);

  const empty = book && book.asks.length === 0 && book.bids.length === 0;

  return (
    <div className="tp book-box">
      <div className="tp-head"><span className="tp-title">Order book</span><span className="tp-sub">ours</span></div>
      <div className="ob-cols"><span>Price(USDT)</span><span className="num">Amount</span><span className="num">Total</span></div>

      {empty && <p className="tp-empty">no liquidity — press “Seed liquidity”</p>}

      <div className="ob-asks">
        {[...(book?.asks ?? [])].slice(0, 12).reverse().map((l, ri, rev) => {
          const i = rev.length - 1 - ri;
          const c = cum(book!.asks, i);
          return (
            <button className="ob-row ask" key={`a${l.price}`} onClick={() => onPick(l.price)} title="Click to set price">
              <span className="bar ask" style={{ width: `${(c / maxTotal) * 100}%` }} />
              <span className="px ask">{Number(l.price).toFixed(2)}</span>
              <span className="num">{trimAmount(l.quantity)}</span>
              <span className="num dim">{c.toFixed(3)}</span>
            </button>
          );
        })}
      </div>

      <div className="ob-mid">
        {live ? <span className={`ob-mid-px`}>{live.toFixed(2)}</span> : <span className="ob-mid-px">—</span>}
        <span className="ob-mid-lbl">live price</span>
      </div>

      <div className="ob-bids">
        {(book?.bids ?? []).slice(0, 12).map((l, i) => {
          const c = cum(book!.bids, i);
          return (
            <button className="ob-row bid" key={`b${l.price}`} onClick={() => onPick(l.price)} title="Click to set price">
              <span className="bar bid" style={{ width: `${(c / maxTotal) * 100}%` }} />
              <span className="px bid">{Number(l.price).toFixed(2)}</span>
              <span className="num">{trimAmount(l.quantity)}</span>
              <span className="num dim">{c.toFixed(3)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- form */

function OrderForm({
  market, symbol, balances, livePrice, clickedPrice,
}: {
  market?: MarketInfo;
  symbol: string;
  balances: Balance[];
  livePrice: number | null;
  clickedPrice: string | null;
}) {
  const [type, setType] = useState<"LIMIT" | "MARKET">("LIMIT");
  // One shared price for both sides (Binance shares the price row). Defaults to live, click-fills.
  const [price, setPrice] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const base = market?.base ?? symbol.replace(/USDT$/, "");
  const quote = market?.quote ?? "USDT";

  useEffect(() => { if (clickedPrice) setPrice(clickedPrice); }, [clickedPrice]);
  useEffect(() => { setPrice((p) => (p === "" && livePrice ? livePrice.toFixed(2) : p)); }, [livePrice]);

  const availOf = (a: string) => Number(balances.find((b) => b.asset === a)?.available ?? "0");

  return (
    <>
      <div className="of-tabs">
        {(["LIMIT", "MARKET"] as const).map((t) => (
          <button key={t} className={type === t ? "on" : ""} onClick={() => setType(t)}>{t === "LIMIT" ? "Limit" : "Market"}</button>
        ))}
        <span className="of-tab-note">no manual entry — price from the book, size from the slider</span>
      </div>

      {/* Buy (green, left) and Sell (red, right) side by side, like Binance. */}
      <div className="of-cols">
        <SideForm
          side="BUY" type={type} symbol={symbol} base={base} quote={quote}
          market={market} price={price} setPrice={setPrice} livePrice={livePrice}
          available={availOf(quote)} baseAvailable={availOf(base)} onNote={setNote}
        />
        <SideForm
          side="SELL" type={type} symbol={symbol} base={base} quote={quote}
          market={market} price={price} setPrice={setPrice} livePrice={livePrice}
          available={availOf(quote)} baseAvailable={availOf(base)} onNote={setNote}
        />
      </div>
      {note && <p className="of-note">{note}</p>}
    </>
  );
}

function SideForm({
  side, type, symbol, base, quote, market, price, setPrice, livePrice, available, baseAvailable, onNote,
}: {
  side: "BUY" | "SELL";
  type: "LIMIT" | "MARKET";
  symbol: string;
  base: string;
  quote: string;
  market?: MarketInfo;
  price: string;
  setPrice: (p: string) => void;
  livePrice: number | null;
  available: number; // quote balance
  baseAvailable: number; // base balance
  onNote: (n: string) => void;
}) {
  const [pct, setPct] = useState(0);
  const [busy, setBusy] = useState(false);
  const step = Number(market?.qty_step ?? "0.0001");

  const refPrice = type === "LIMIT" && price ? Number(price) : livePrice ?? 0;
  const maxQty = side === "BUY" ? (refPrice > 0 ? available / refPrice : 0) : baseAvailable;
  const qty = maxQty > 0 ? Math.floor((maxQty * (pct / 100)) / step) * step : 0;
  const qtyStr = qty > 0 ? String(Number(qty.toFixed(8))) : "";
  const total = refPrice > 0 && qty > 0 ? refPrice * qty : 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (qty <= 0) { onNote("choose an amount with the slider"); return; }
    setBusy(true);
    onNote("");
    try {
      const o = await api.placeOrder({ symbol, side, type, quantity: qtyStr, price: type === "LIMIT" ? price : null });
      onNote(`${side} ${o.status} — filled ${trimAmount(o.filled_quantity)}/${trimAmount(o.quantity)} ${base}`);
      setPct(0);
      window.dispatchEvent(new CustomEvent("orders-changed"));
      window.dispatchEvent(new CustomEvent("book-changed"));
    } catch (err) {
      onNote(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="of-col" onSubmit={submit}>
      <div className="of-field">
        <label>Price</label>
        {type === "MARKET" ? (
          <div className="of-market-px">Market</div>
        ) : (
          <div className="of-input">
            <input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" />
            <span className="of-unit">{quote}</span>
          </div>
        )}
      </div>

      <div className="of-field">
        <label>Amount</label>
        <div className="of-input readonly">
          <input value={qtyStr} readOnly placeholder="0" />
          <span className="of-unit">{base}</span>
        </div>
      </div>

      <div className="of-slider">
        <input type="range" min={0} max={100} step={1} value={pct}
               onChange={(e) => setPct(Number(e.target.value))} className={side.toLowerCase()} />
        <div className="of-pcts">
          {[0, 25, 50, 75, 100].map((p) => (
            <button type="button" key={p} className={pct === p ? "on" : ""} onClick={() => setPct(p)}>{p}%</button>
          ))}
        </div>
      </div>

      <div className="of-row"><span>Avbl</span><span className="mono">{side === "BUY" ? `${available.toFixed(2)} ${quote}` : `${trimAmount(baseAvailable.toString())} ${base}`}</span></div>
      <div className="of-row"><span>Total</span><span className="mono">{total > 0 ? `${total.toFixed(2)} ${quote}` : `Min ${trimAmount(market?.min_notional ?? "5")} ${quote}`}</span></div>

      <button className={`of-submit ${side.toLowerCase()}`} disabled={busy}>
        {busy ? "…" : `${side === "BUY" ? "Buy" : "Sell"} ${base}`}
      </button>
    </form>
  );
}

/* ---------------------------------------------------------------- trades */

function RecentTrades({ symbol }: { symbol: string }) {
  const [trades, setTrades] = useState<TradeTick[]>([]);
  usePoll(() => { api.marketTrades(symbol).then(setTrades).catch(() => setTrades([])); }, 1500);

  return (
    <div className="tp trades-box">
      <div className="tp-head"><span className="tp-title">Market trades</span><span className="tp-sub">ours</span></div>
      <div className="mt-cols"><span>Price(USDT)</span><span className="num">Amount({symbol.replace(/USDT$/, "")})</span><span className="num">Time</span></div>
      <div className="mt-list">
        {trades.length === 0 && <p className="tp-empty">no trades yet</p>}
        {trades.map((t) => (
          <div className="mt-row" key={t.id}>
            <span className={t.taker_side === "BUY" ? "px bid" : "px ask"}>{Number(t.price).toFixed(2)}</span>
            <span className="num">{trimAmount(t.quantity)}</span>
            <span className="num dim">{new Date(t.created_at).toLocaleTimeString("en-GB")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ open orders */

function OpenOrders({ symbol }: { symbol: string }) {
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const load = useCallback(() => { api.openOrders().then(setOrders).catch(() => setOrders([])); }, []);
  usePoll(load, 2500);
  useEffect(() => {
    const h = () => load();
    window.addEventListener("orders-changed", h);
    return () => window.removeEventListener("orders-changed", h);
  }, [load]);

  async function cancel(id: number) {
    try { await api.cancelOrder(id); load(); window.dispatchEvent(new CustomEvent("book-changed")); } catch { /* ignore */ }
  }

  const rows = orders.filter((o) => o.symbol === symbol);

  return (
    <>
      <div className="tp-head"><span className="tp-title">Open orders ({rows.length})</span></div>
      <div className="oo-table">
        <div className="oo-h"><span>Side</span><span className="num">Price</span><span className="num">Amount</span><span className="num">Filled</span><span></span></div>
        {rows.length === 0 && <p className="tp-empty">no open orders</p>}
        {rows.map((o) => (
          <div className="oo-r" key={o.id}>
            <span className={o.side === "BUY" ? "bid" : "ask"}>{o.side} {o.type}</span>
            <span className="num">{o.price ? Number(o.price).toFixed(2) : "mkt"}</span>
            <span className="num">{trimAmount(o.quantity)}</span>
            <span className="num dim">{trimAmount(o.filled_quantity)}</span>
            <span className="num"><button className="cancel" onClick={() => cancel(o.id)}>✕</button></span>
          </div>
        ))}
      </div>
    </>
  );
}
