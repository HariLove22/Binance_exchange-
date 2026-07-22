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
  const ticker = useTicker(symbol);
  const up = (ticker?.changePercent ?? 0) >= 0;

  return (
    <div className="trade">
      {/* symbol + live ticker header */}
      <div className="tk-bar">
        <select className="sym-pick" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {markets.map((m) => (
            <option key={m.symbol} value={m.symbol}>{m.symbol}</option>
          ))}
        </select>
        {ticker ? (
          <>
            <span className={`tk-price ${up ? "bid" : "ask"}`}>{ticker.price.toFixed(2)}</span>
            <div className="tk-stats">
              <span className={`tk-chg ${up ? "bid" : "ask"}`}>{up ? "+" : ""}{ticker.changePercent.toFixed(2)}%</span>
              <span className="tk-s"><i>24h High</i>{ticker.high.toFixed(2)}</span>
              <span className="tk-s"><i>24h Low</i>{ticker.low.toFixed(2)}</span>
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

      <div className="term">
        <aside className="term-left">
          <OrderBookPanel symbol={symbol} onPick={setClickedPrice} live={ticker?.price ?? null} />
        </aside>

        <main className="term-center">
          <section className="tp chart-box">
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
          <section className="tp orders-box">
            <OpenOrders symbol={symbol} />
          </section>
        </main>

        <aside className="term-right">
          <OrderForm
            market={market}
            symbol={symbol}
            balances={balances}
            livePrice={ticker?.price ?? null}
            clickedPrice={clickedPrice}
          />
        </aside>
      </div>

      <RecentTrades symbol={symbol} />
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
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [type, setType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState("");
  const [pct, setPct] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const base = market?.base ?? symbol.replace(/USDT$/, "");
  const quote = market?.quote ?? "USDT";
  const step = Number(market?.qty_step ?? "0.0001");

  // Price defaults to the live price and follows order-book clicks. Never something to type.
  useEffect(() => { if (clickedPrice) setPrice(clickedPrice); }, [clickedPrice]);
  useEffect(() => {
    setPrice((p) => (p === "" && livePrice ? livePrice.toFixed(2) : p));
  }, [livePrice]);

  const availOf = (a: string) => Number(balances.find((b) => b.asset === a)?.available ?? "0");
  const quoteAvail = availOf(quote);
  const baseAvail = availOf(base);

  const refPrice = type === "LIMIT" && price ? Number(price) : livePrice ?? 0;
  const maxQty = side === "BUY" ? (refPrice > 0 ? quoteAvail / refPrice : 0) : baseAvail;

  // Amount comes from the slider (% of what the account holds), floored to a whole lot step.
  const qty = maxQty > 0 ? Math.floor((maxQty * (pct / 100)) / step) * step : 0;
  const qtyStr = qty > 0 ? String(Number(qty.toFixed(8))) : "";
  const total = refPrice > 0 && qty > 0 ? refPrice * qty : 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (qty <= 0) { setNote("choose an amount with the slider"); return; }
    setBusy(true);
    setNote(null);
    try {
      const o = await api.placeOrder({ symbol, side, type, quantity: qtyStr, price: type === "LIMIT" ? price : null });
      setNote(`${side} ${o.status} — filled ${trimAmount(o.filled_quantity)}/${trimAmount(o.quantity)} ${base}`);
      setPct(0);
      window.dispatchEvent(new CustomEvent("orders-changed"));
      window.dispatchEvent(new CustomEvent("book-changed"));
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tp form-box">
      <div className="of-tabs">
        {(["LIMIT", "MARKET"] as const).map((t) => (
          <button key={t} className={type === t ? "on" : ""} onClick={() => setType(t)}>{t === "LIMIT" ? "Limit" : "Market"}</button>
        ))}
      </div>

      <div className="of-side">
        {(["BUY", "SELL"] as const).map((s) => (
          <button key={s} className={`${s.toLowerCase()} ${side === s ? "on" : ""}`} onClick={() => { setSide(s); setPct(0); }}>{s === "BUY" ? "Buy" : "Sell"}</button>
        ))}
      </div>

      <form onSubmit={submit}>
        <div className="of-field">
          <label>Price</label>
          {type === "MARKET" ? (
            <div className="of-market-px">Market · {livePrice ? livePrice.toFixed(2) : "—"} <span>{quote}</span></div>
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

        {/* Slider over the account's available balance — how you actually size a trade. */}
        <div className="of-slider">
          <input type="range" min={0} max={100} step={1} value={pct} onChange={(e) => setPct(Number(e.target.value))}
                 className={side === "BUY" ? "buy" : "sell"} />
          <div className="of-pcts">
            {[0, 25, 50, 75, 100].map((p) => (
              <button type="button" key={p} className={pct === p ? "on" : ""} onClick={() => setPct(p)}>{p}%</button>
            ))}
          </div>
        </div>

        <div className="of-row"><span>Available</span><span className="mono">{side === "BUY" ? `${quoteAvail.toFixed(2)} ${quote}` : `${trimAmount(baseAvail.toString())} ${base}`}</span></div>
        <div className="of-row"><span>{side === "BUY" ? "Cost" : "Proceeds"}</span><span className="mono">{total > 0 ? `${total.toFixed(2)} ${quote}` : `— ${quote}`}</span></div>

        <button className={`of-submit ${side.toLowerCase()}`} disabled={busy}>
          {busy ? "…" : `${side === "BUY" ? "Buy" : "Sell"} ${base}`}
        </button>
      </form>
      {note && <p className="of-note">{note}</p>}
    </div>
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
