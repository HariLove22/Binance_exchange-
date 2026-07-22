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
 * The spot trading panel — chart, order book, order form, open orders, recent trades.
 *
 * The chart is Binance's reference price history; the order book and trades are ours. The order
 * form places a real order against our engine, which settles to the ledger. "Seed liquidity" runs
 * the dev market-maker refresh so there is something to trade against.
 */
export function Trade() {
  const [markets, setMarkets] = useState<MarketInfo[]>([]);
  const [symbol, setSymbol] = useState("ETHUSDT");
  const [interval, setInterval] = useState("1m");
  const [balances, setBalances] = useState<Balance[]>([]);

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

  // Refresh balances whenever an order changes them.
  useEffect(() => {
    const h = () => loadBalances();
    window.addEventListener("orders-changed", h);
    return () => window.removeEventListener("orders-changed", h);
  }, [loadBalances]);

  const market = markets.find((m) => m.symbol === symbol);
  const ticker = useTicker(symbol); // LIVE price from Binance WS
  const up = (ticker?.changePercent ?? 0) >= 0;

  return (
    <div className="trade">
      <div className="trade-top">
        <select className="sym-pick" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {markets.map((m) => (
            <option key={m.symbol} value={m.symbol}>{m.symbol}</option>
          ))}
        </select>

        {ticker && (
          <div className="live-ticker">
            <span className={`lt-price ${up ? "bid" : "ask"}`}>{ticker.price.toFixed(2)}</span>
            <span className={`lt-chg ${up ? "bid" : "ask"}`}>
              {up ? "+" : ""}{ticker.changePercent.toFixed(2)}%
            </span>
            <span className="lt-stat">24h H <b>{ticker.high.toFixed(2)}</b></span>
            <span className="lt-stat">24h L <b>{ticker.low.toFixed(2)}</b></span>
            <span className="lt-live">● live</span>
          </div>
        )}

        <SeedLiquidity />
      </div>

      <div className="trade-grid">
        <section className="tp chart-panel">
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

        <section className="tp book-panel">
          <OrderBookPanel symbol={symbol} />
        </section>

        <section className="tp form-panel">
          <OrderForm market={market} symbol={symbol} balances={balances} livePrice={ticker?.price ?? null} />
        </section>

        <section className="tp trades-panel">
          <RecentTrades symbol={symbol} />
        </section>

        <section className="tp orders-panel">
          <OpenOrders symbol={symbol} />
        </section>
      </div>
    </div>
  );
}

function SeedLiquidity() {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  return (
    <div className="seed">
      <button
        className="btn-outline-d"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setNote(null);
          try {
            const r = await api.refreshMarketMaker();
            setNote(`liquidity seeded: ${Object.entries(r).map(([s, n]) => `${s}=${n}`).join(" ")}`);
          } catch (e) {
            setNote(e instanceof ApiError ? e.message : String(e));
          } finally {
            setBusy(false);
          }
        }}
        title="Dev: fund the market maker and re-quote around the live Binance price"
      >
        {busy ? "…" : "Seed liquidity"}
      </button>
      {note && <span className="seed-note">{note}</span>}
    </div>
  );
}

/* ------------------------------------------------------------------- book */

function usePoll(fn: () => void, ms: number) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    saved.current();
    const id = window.setInterval(() => saved.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}

function OrderBookPanel({ symbol }: { symbol: string }) {
  const [book, setBook] = useState<OrderBook | null>(null);
  usePoll(() => {
    api.orderBook(symbol).then(setBook).catch(() => setBook(null));
  }, 2000);

  const maxQty = Math.max(
    ...(book?.asks ?? []).map((l) => Number(l.quantity)),
    ...(book?.bids ?? []).map((l) => Number(l.quantity)),
    1,
  );

  return (
    <>
      <div className="tp-head"><span className="tp-title">Order book</span><span className="tp-sub">ours</span></div>
      <div className="ob">
        <div className="ob-cols"><span>Price</span><span className="num">Size</span></div>
        <div className="ob-side">
          {[...(book?.asks ?? [])].reverse().map((l, i) => (
            <div className="ob-row" key={`a${i}`}>
              <span className="bar ask" style={{ width: `${(Number(l.quantity) / maxQty) * 100}%` }} />
              <span className="px ask">{Number(l.price).toFixed(2)}</span>
              <span className="num">{trimAmount(l.quantity)}</span>
            </div>
          ))}
        </div>
        <div className="ob-spread">
          {book && book.asks[0] && book.bids[0]
            ? `spread ${(Number(book.asks[0].price) - Number(book.bids[0].price)).toFixed(2)}`
            : "no liquidity — seed it"}
        </div>
        <div className="ob-side">
          {(book?.bids ?? []).map((l, i) => (
            <div className="ob-row" key={`b${i}`}>
              <span className="bar bid" style={{ width: `${(Number(l.quantity) / maxQty) * 100}%` }} />
              <span className="px bid">{Number(l.price).toFixed(2)}</span>
              <span className="num">{trimAmount(l.quantity)}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------- form */

function OrderForm({
  market, symbol, balances, livePrice,
}: {
  market?: MarketInfo;
  symbol: string;
  balances: Balance[];
  livePrice: number | null;
}) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [type, setType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState("");
  const [qty, setQty] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const base = market?.base ?? symbol.replace(/USDT$/, "");
  const quote = market?.quote ?? "USDT";

  const availableOf = (asset: string) => Number(balances.find((b) => b.asset === asset)?.available ?? "0");
  const quoteAvail = availableOf(quote); // spend this on a BUY
  const baseAvail = availableOf(base); // sell this on a SELL

  // The price used for sizing: the limit price if set, else the live price.
  const refPrice = type === "LIMIT" && price ? Number(price) : livePrice ?? 0;

  // Trade with what's actually in the account: BUY is limited by quote balance, SELL by base.
  const maxQty = side === "BUY" ? (refPrice > 0 ? quoteAvail / refPrice : 0) : baseAvail;

  function setPercent(pct: number) {
    if (maxQty <= 0) return;
    const step = Number(market?.qty_step ?? "0.0001");
    let q = maxQty * pct;
    // Round down to a whole number of steps so it never exceeds the balance.
    q = Math.floor(q / step) * step;
    setQty(q > 0 ? String(Number(q.toFixed(8))) : "");
  }

  const estCost = refPrice > 0 && qty ? refPrice * Number(qty) : 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setNote(null);
    try {
      const o = await api.placeOrder({
        symbol, side, type, quantity: qty,
        price: type === "LIMIT" ? price : null,
      });
      setNote(`order #${o.id} ${o.status} — filled ${trimAmount(o.filled_quantity)}/${trimAmount(o.quantity)}`);
      setQty("");
      window.dispatchEvent(new CustomEvent("orders-changed"));
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="tp-head"><span className="tp-title">Order</span></div>
      <div className="side-toggle">
        {(["BUY", "SELL"] as const).map((s) => (
          <button key={s} className={`${s.toLowerCase()} ${side === s ? "on" : ""}`} onClick={() => setSide(s)}>{s}</button>
        ))}
      </div>
      <div className="type-toggle">
        {(["LIMIT", "MARKET"] as const).map((t) => (
          <button key={t} className={type === t ? "on" : ""} onClick={() => setType(t)}>{t}</button>
        ))}
      </div>

      {/* What this account can spend/sell, live. */}
      <div className="avail-row">
        Available: <b>{side === "BUY" ? `${quoteAvail.toFixed(2)} ${quote}` : `${trimAmount(baseAvail.toString())} ${base}`}</b>
      </div>

      <form onSubmit={submit}>
        {type === "LIMIT" && (
          <label className="fld">
            <span>Price</span>
            <input value={price} onChange={(e) => setPrice(e.target.value)}
                   placeholder={livePrice ? livePrice.toFixed(2) : ""} inputMode="decimal" required />
            <span className="unit">{quote}</span>
          </label>
        )}
        <label className="fld">
          <span>Amount</span>
          <input value={qty} onChange={(e) => setQty(e.target.value)} inputMode="decimal" required />
          <span className="unit">{base}</span>
        </label>

        <div className="pct-row">
          {[0.25, 0.5, 0.75, 1].map((p) => (
            <button type="button" key={p} onClick={() => setPercent(p)}>{p * 100}%</button>
          ))}
        </div>

        <div className="est-row">
          <span>{side === "BUY" ? "Cost" : "Proceeds"}</span>
          <span className="mono">{estCost > 0 ? `${estCost.toFixed(2)} ${quote}` : "—"}</span>
        </div>

        <button className={`submit ${side.toLowerCase()}`} disabled={busy}>
          {busy ? "…" : `${side} ${base}`}
        </button>
      </form>
      {note && <p className="form-note">{note}</p>}
      {market && (
        <p className="form-hint">
          tick {trimAmount(market.price_tick)} · step {trimAmount(market.qty_step)} · min {trimAmount(market.min_notional)} {quote} · taker fee {(Number(market.taker_fee) * 100).toFixed(2)}%
        </p>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- trades */

function RecentTrades({ symbol }: { symbol: string }) {
  const [trades, setTrades] = useState<TradeTick[]>([]);
  usePoll(() => {
    api.marketTrades(symbol).then(setTrades).catch(() => setTrades([]));
  }, 2000);

  return (
    <>
      <div className="tp-head"><span className="tp-title">Trades</span><span className="tp-sub">ours</span></div>
      <div className="trades-list">
        {trades.length === 0 && <p className="tp-empty">no trades yet</p>}
        {trades.map((t) => (
          <div className="trade-row" key={t.id}>
            <span className={t.taker_side === "BUY" ? "px bid" : "px ask"}>{Number(t.price).toFixed(2)}</span>
            <span className="num">{trimAmount(t.quantity)}</span>
            <span className="num dim">{new Date(t.created_at).toLocaleTimeString("en-GB")}</span>
          </div>
        ))}
      </div>
    </>
  );
}

/* ------------------------------------------------------------ open orders */

function OpenOrders({ symbol }: { symbol: string }) {
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const load = useCallback(() => {
    api.openOrders().then(setOrders).catch(() => setOrders([]));
  }, []);
  usePoll(load, 3000);
  useEffect(() => {
    const h = () => load();
    window.addEventListener("orders-changed", h);
    return () => window.removeEventListener("orders-changed", h);
  }, [load]);

  async function cancel(id: number) {
    try {
      await api.cancelOrder(id);
      load();
    } catch { /* ignore */ }
  }

  const rows = orders.filter((o) => o.symbol === symbol);

  return (
    <>
      <div className="tp-head"><span className="tp-title">Open orders</span></div>
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
