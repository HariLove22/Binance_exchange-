import { Fragment, useCallback, useEffect, useState } from "react";
import { api, ApiError, trimAmount, type FuturesAccount, type FuturesClosedPosition, type FuturesOpenOrder, type MarketInfo, type OrderBook, type TradeTick } from "../lib/api";
import { useTicker } from "../lib/useLive";
import { useMarketWs } from "../lib/marketWs";
import { TradeChart } from "./TradeChart";
import { OrderBookPanel, RecentTrades, MarketList, fmtPx, INTERVALS } from "./Trade";
import { useKycApproved, KycRequiredNotice } from "./KycGate";
import "./trade.css";
import "./margin-term.css";
import "./futures.css";

/**
 * Futures terminal — perpetuals on the spot terminal shell. Long/short with leverage, margin in the
 * futures wallet, live PnL and liquidation price per position. Mark-price fills against the house.
 */
export function FuturesTrade() {
  const [markets, setMarkets] = useState<MarketInfo[]>([]);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("1m");
  const [acct, setAcct] = useState<FuturesAccount | null>(null);
  const [, setClickedPrice] = useState<string | null>(null);
  const [xfer, setXfer] = useState(false);
  const [mode, setMode] = useState<"USDTM" | "COINM">("USDTM");

  useEffect(() => { api.marketSymbols().then(setMarkets).catch(() => {}); }, []);
  const loadAcct = useCallback(() => api.futuresAccount().then(setAcct).catch(() => {}), []);
  useEffect(() => { loadAcct(); const t = window.setInterval(loadAcct, 4000); return () => window.clearInterval(t); }, [loadAcct]);

  const market = markets.find((m) => m.symbol === symbol);
  const tradeable = market !== undefined;
  const ticker = useTicker(symbol);
  const up = (ticker?.changePercent ?? 0) >= 0;
  const { book, trades } = useMarketWs(tradeable ? symbol : null);
  const kycOk = useKycApproved();

  const base = symbol.replace(/USDT$/, "");
  const inverse = mode === "COINM";
  const coinBal = Number(acct?.balances?.[base] ?? 0);
  const usdtBal = Number(acct?.balance_usdt ?? 0);
  // Account summary for the current margin mode: available + locked margin + unrealized PnL = equity.
  const availBal = inverse ? coinBal : usdtBal;
  const modePos = (acct?.positions ?? []).filter((p) => p.inverse === inverse);
  const upnl = modePos.reduce((s, p) => s + Number(p.unrealized_pnl ?? 0), 0);
  const lockedMargin = modePos.reduce((s, p) => s + Number(p.margin ?? 0), 0);
  const fmtBal = (v: number) => (inverse ? `${v.toFixed(4)} ${base}` : `${v.toFixed(2)} USDT`);

  return (
    <div className="trade">
      {xfer && <TransferModal asset={inverse ? base : "USDT"} onClose={() => setXfer(false)} onDone={(a) => { setAcct(a); setXfer(false); }} />}
      <div className="term-grid mgt">
        <div className="g-ticker tk-bar">
          <div className="tk-symbol">
            <span className="mgt-lev">PERP</span>
            <div className="fut-mode">
              <button className={mode === "USDTM" ? "on" : ""} onClick={() => setMode("USDTM")}>USDⓈ-M</button>
              <button className={mode === "COINM" ? "on" : ""} onClick={() => setMode("COINM")}>COIN-M</button>
            </div>
          </div>
          {ticker ? (
            <>
              <span className={`tk-price ${up ? "bid" : "ask"}`}>{fmtPx(ticker.price)}</span>
              <div className="tk-stats">
                <span className={`tk-chg ${up ? "bid" : "ask"}`}>{up ? "+" : ""}{ticker.changePercent.toFixed(2)}%</span>
                <span className="tk-s"><i>24h High</i>{fmtPx(ticker.high)}</span>
                <span className="tk-s"><i>24h Low</i>{fmtPx(ticker.low)}</span>
              </div>
            </>
          ) : <span className="tk-loading">connecting…</span>}
          <div className="tk-spacer" />
          <div className="mgt-ml"><span>Margin Balance</span><b title="Available + locked margin + unrealized PnL">{acct ? fmtBal(availBal + lockedMargin + upnl) : "—"}</b></div>
          <div className="mgt-ml"><span>Unrealized PnL</span><b className={upnl > 0 ? "up" : upnl < 0 ? "down" : ""}>{acct ? `${upnl >= 0 ? "+" : ""}${fmtBal(upnl)}` : "—"}</b></div>
          <div className="mgt-ml"><span>Available</span><b>{acct ? fmtBal(availBal) : "—"}</b></div>
          {/* Dev only: one click to fund spot + auto-approve KYC so a position can be opened instantly. */}
          <button className="mgt-hbtn" title="Dev: credit 50k USDT + approve KYC" onClick={() => { void api.futuresDevSetup().then(loadAcct).catch(() => {}); }}>Dev fund</button>
          <button className="mgt-hbtn" onClick={() => setXfer(true)}>Transfer</button>
        </div>

        <aside className="g-left">
          {tradeable ? (
            <OrderBookPanel book={book} onPick={setClickedPrice} live={ticker?.price ?? null} />
          ) : <div className="tp fill"><div className="tp-head"><span className="tp-title">Order book</span></div><p className="tp-empty">List this pair on Spot first.</p></div>}
        </aside>

        <section className="g-chart tp">
          <div className="tp-head"><span className="tp-title">{symbol} · Perp</span>
            <div className="ivals">{INTERVALS.map((i) => <button key={i} className={interval === i ? "on" : ""} onClick={() => setInterval(i)}>{i}</button>)}</div>
          </div>
          <TradeChart symbol={symbol} interval={interval} />
        </section>

        <section className="g-form tp">
          {kycOk === false ? <KycRequiredNotice /> :
            <FuturesForm symbol={symbol} inverse={inverse} balance={inverse ? coinBal : usdtBal}
                         livePrice={ticker?.price ?? null} book={book} onDone={loadAcct} />}
        </section>

        <aside className="g-market"><MarketList current={symbol} onPick={setSymbol} inverse={inverse} /></aside>

        <section className="g-orders tp">
          <Positions acct={acct} onDone={loadAcct} symbol={symbol} trades={trades} />
        </section>
      </div>
    </div>
  );
}

function FuturesForm({ symbol, inverse, balance, livePrice, book, onDone }: { symbol: string; inverse: boolean; balance: number; livePrice: number | null; book: OrderBook | null; onDone: () => void }) {
  const [lev, setLev] = useState("10");
  const [pct, setPct] = useState(0);
  const [sizeInput, setSizeInput] = useState("");
  const [cross, setCross] = useState(false);
  const [otype, setOtype] = useState<"MARKET" | "LIMIT" | "STOP">("MARKET");
  const [limitPrice, setLimitPrice] = useState("");
  const [triggerPrice, setTriggerPrice] = useState("");
  const [busy, setBusy] = useState<"LONG" | "SHORT" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const base = symbol.replace(/USDT$/, "");
  // A LIMIT sizes off its limit price, a STOP off its trigger price, a market off the live price.
  const refPrice = otype === "LIMIT" ? Number(limitPrice) : otype === "STOP" ? Number(triggerPrice) : 0;
  const price = refPrice > 0 ? refPrice : (livePrice ?? 0);
  const leverage = Number(lev) || 1;
  // COIN-M: balance is in coin; size = USD notional, margin in coin. USDT-M: size = base qty, margin USDT.
  const marginUnit = inverse ? base : "USDT";
  const sizeUnit = inverse ? "USD" : base;
  // Size is a typed input; the % slider just fills it from the max the balance allows.
  // Inverse: size = USD notional. Linear: size = base qty.
  const maxNotionalUsd = price > 0 ? balance * (inverse ? price : 1) * leverage : 0;
  const maxSize = inverse ? maxNotionalUsd : (price > 0 ? maxNotionalUsd / price : 0);
  const size = Number(sizeInput) || 0;
  const margin = price > 0 && size > 0 ? (inverse ? (size / price) / leverage : (size * price) / leverage) : 0;
  // Live estimates (same maths the server uses). entry ≈ the ref price; shown for both sides since
  // the side isn't chosen until Buy/Sell is clicked. MMR 0.5%, taker fee 0.04%.
  const estLiq = (side: "LONG" | "SHORT") => {
    if (price <= 0 || size <= 0 || margin <= 0) return 0;
    const mmr = 0.005;
    if (inverse) {
      if (side === "LONG") return (size * (1 + mmr)) / (margin + size / price);
      const denom = size / price - margin;
      return denom > 0 ? (size * (1 - mmr)) / denom : 0;
    }
    if (side === "LONG") return (price * size - margin) / (size * (1 - mmr));
    return (margin + price * size) / (size * (1 + mmr));
  };
  const fee = size > 0 && price > 0 ? (inverse ? size / price : size * price) * 0.0004 : 0;
  const px = (v: number) => (v > 0 ? fmtPx(v) : "—");
  // Track B1 preview: VWAP the visible book for a slippage-aware fill price (same walk as the
  // server). A LONG lifts asks, a SHORT hits bids. Only meaningful for a MARKET order.
  const estEntry = (side: "LONG" | "SHORT") => {
    const levels = side === "LONG" ? book?.asks : book?.bids; // asks lowest-first, bids highest-first
    let need = inverse ? (price > 0 ? size / price : 0) : size;
    if (!levels?.length || need <= 0) return 0;
    let cost = 0, filled = 0;
    for (const l of levels) {
      if (need <= 0) break;
      const take = Math.min(need, Number(l.quantity));
      cost += take * Number(l.price); filled += take; need -= take;
    }
    return need > 0 || filled <= 0 ? 0 : cost / filled; // 0 = book too thin
  };
  const applyPct = (p: number) => {
    setPct(p);
    const s = (maxSize * p) / 100;
    setSizeInput(s > 0 ? String(Number(s.toFixed(inverse ? 2 : 6))) : "");
  };

  async function submit(side: "LONG" | "SHORT") {
    if (size <= 0) { setNote("choose a size with the slider"); return; }
    if (otype === "LIMIT" && !(Number(limitPrice) > 0)) { setNote("enter a limit price"); return; }
    if (otype === "STOP" && !(Number(triggerPrice) > 0)) { setNote("enter a trigger price"); return; }
    setBusy(side); setNote("");
    try {
      const o = await api.futuresOrder({ symbol, side, size: sizeInput, leverage: lev, inverse, cross,
                                         type: otype === "STOP" ? "STOP_MARKET" : otype,
                                         price: otype === "LIMIT" ? limitPrice : undefined,
                                         trigger_price: otype === "STOP" ? triggerPrice : undefined });
      setNote(otype === "LIMIT" ? `${side} limit resting @ ${trimAmount(limitPrice)}`
        : otype === "STOP" ? `${side} stop resting — fires at market @ ${trimAmount(triggerPrice)}`
        : `${side} opened @ ${trimAmount(o.entry_price ?? "0")} · margin ${trimAmount(o.margin ?? "0")} ${o.margin_asset ?? ""}`);
      setPct(0); setSizeInput(""); onDone();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(null); }
  }

  return (
    <div className="fut-form">
      <div className="fut-mode-row">
        <div className="fut-mode">
          <button className={!cross ? "on" : ""} onClick={() => setCross(false)}>Isolated</button>
          <button className={cross ? "on" : ""} onClick={() => setCross(true)}>Cross</button>
        </div>
        <div className="fut-mode">
          <button className={otype === "MARKET" ? "on" : ""} onClick={() => setOtype("MARKET")}>Market</button>
          <button className={otype === "LIMIT" ? "on" : ""} onClick={() => setOtype("LIMIT")}>Limit</button>
          <button className={otype === "STOP" ? "on" : ""} onClick={() => setOtype("STOP")}>Stop</button>
        </div>
      </div>
      {otype === "LIMIT" && (
        <div className="of-field"><label>Limit price</label>
          <div className="of-input"><input value={limitPrice} onChange={(e) => setLimitPrice(e.target.value.replace(/[^\d.]/g, ""))} placeholder="0" inputMode="decimal" /><span className="of-unit">USDT</span></div>
        </div>
      )}
      {otype === "STOP" && (
        <div className="of-field"><label>Trigger price</label>
          <div className="of-input"><input value={triggerPrice} onChange={(e) => setTriggerPrice(e.target.value.replace(/[^\d.]/g, ""))} placeholder="0" inputMode="decimal" /><span className="of-unit">USDT</span></div>
        </div>
      )}
      <div className="fut-lev">
        <label>Leverage</label>
        <div className="fut-lev-row">
          <input type="range" min={1} max={100} value={lev} onChange={(e) => setLev(e.target.value)} />
          <span className="fut-lev-val">{lev}x</span>
        </div>
      </div>
      <div className="of-field"><label>Size ({sizeUnit})</label>
        <div className="of-input"><input value={sizeInput} onChange={(e) => setSizeInput(e.target.value.replace(/[^\d.]/g, ""))} placeholder="0" inputMode="decimal" /><span className="of-unit">{sizeUnit}</span></div>
      </div>
      <div className="of-slider">
        <input type="range" min={0} max={100} step={1} value={pct} onChange={(e) => applyPct(Number(e.target.value))} />
        <div className="of-pcts">{[0, 25, 50, 75, 100].map((p) => <button key={p} className={pct === p ? "on" : ""} onClick={() => applyPct(p)}>{p}%</button>)}</div>
      </div>
      <div className="of-row">
        <span>Avbl <span className="mono">{inverse ? `${balance.toFixed(4)} ${base}` : `${balance.toFixed(2)} USDT`}</span></span>
        <span>Margin <span className="mono">{margin > 0 ? `${inverse ? trimAmount(String(Number(margin.toFixed(8)))) : margin.toFixed(2)} ${marginUnit}` : "—"}</span></span>
      </div>
      {otype === "MARKET" && size > 0 && (estEntry("LONG") > 0 || estEntry("SHORT") > 0) && (
        <div className="of-row of-est">
          <span title="Estimated fill price walking the live book — bigger size slips further">Entry est. <span className="mono">L {px(estEntry("LONG"))} · S {px(estEntry("SHORT"))}</span></span>
        </div>
      )}
      {size > 0 && price > 0 && (
        <div className="of-row of-est">
          <span title="Estimated liquidation price for a Long / Short at this size and leverage">Liq. est. <span className="mono">L {px(estLiq("LONG"))} · S {px(estLiq("SHORT"))}</span></span>
          <span title="Taker fee (0.04%), charged on close">Fee <span className="mono">{inverse ? `${trimAmount(String(Number(fee.toFixed(8))))} ${base}` : `${fee.toFixed(2)} USDT`}</span></span>
        </div>
      )}
      <div className="fut-btns">
        <button className="fut-long" disabled={busy !== null} onClick={() => submit("LONG")}>{busy === "LONG" ? "…" : "Buy / Long"}</button>
        <button className="fut-short" disabled={busy !== null} onClick={() => submit("SHORT")}>{busy === "SHORT" ? "…" : "Sell / Short"}</button>
      </div>
      {note && <p className="of-note">{note}</p>}
    </div>
  );
}

function Positions({ acct, onDone, symbol, trades }: { acct: FuturesAccount | null; onDone: () => void; symbol: string; trades: TradeTick[] }) {
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"pos" | "orders" | "closed" | "trades">("pos");
  const [orders, setOrders] = useState<FuturesOpenOrder[]>([]);
  const [closed, setClosed] = useState<FuturesClosedPosition[]>([]);
  const loadOrders = useCallback(() => api.futuresOpenOrders().then(setOrders).catch(() => {}), []);
  useEffect(() => { loadOrders(); const t = window.setInterval(loadOrders, 4000); return () => window.clearInterval(t); }, [loadOrders]);
  // Closed positions refresh when the tab is opened and whenever a position is closed (onDone bumps acct).
  useEffect(() => { if (tab === "closed") api.futuresClosed().then(setClosed).catch(() => {}); }, [tab, acct]);
  async function run(fn: () => Promise<unknown>) {
    setErr(null);
    try { await fn(); onDone(); loadOrders(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }
  // Inline editor: one open at a time, keyed by position. `a` is the single value (margin/leverage
  // or take-profit); `b` is the stop-loss when the kind is tpsl.
  const [edit, setEdit] = useState<null | { id: number; kind: "addM" | "remM" | "lev" | "tpsl" }>(null);
  const [ev, setEv] = useState({ a: "", b: "" });
  const num = (s: string) => s.replace(/[^\d.]/g, "");
  function openEdit(id: number, kind: "addM" | "remM" | "lev" | "tpsl", presetA = "") {
    setErr(null); setEv({ a: presetA, b: "" }); setEdit({ id, kind });
  }
  function commitEdit(p: FuturesAccount["positions"][number]) {
    if (!edit) return;
    const { a, b } = ev;
    if (edit.kind === "addM" || edit.kind === "remM") {
      if (!(Number(a) > 0)) return;
      void run(() => api.futuresAdjustMargin(p.id, a, edit.kind === "addM"));
    } else if (edit.kind === "lev") {
      if (!(Number(a) >= 1)) return;
      void run(() => api.futuresSetLeverage(p.id, a));
    } else {
      // TP/SL as reduce-only triggers; closing side is the opposite of the position. Direction (TP
      // fires in profit, SL in loss) is derived server-side from type+side.
      const closeSide: "LONG" | "SHORT" = p.side === "LONG" ? "SHORT" : "LONG";
      const base = { symbol: p.symbol, side: closeSide, size: trimAmount(p.size), leverage: trimAmount(p.leverage),
                     inverse: p.inverse, cross: p.cross, reduce_only: true } as const;
      const jobs: Promise<unknown>[] = [];
      if (Number(a) > 0) jobs.push(api.futuresOrder({ ...base, type: "TAKE_PROFIT", trigger_price: a }));
      if (Number(b) > 0) jobs.push(api.futuresOrder({ ...base, type: "STOP_MARKET", trigger_price: b }));
      if (!jobs.length) return;
      void run(() => Promise.all(jobs));
    }
    setEdit(null);
  }
  const positions = acct?.positions ?? [];
  return (
    <>
      <div className="oo-tabs">
        <button className={tab === "pos" ? "on" : ""} onClick={() => setTab("pos")}>Positions ({positions.length})</button>
        <button className={tab === "orders" ? "on" : ""} onClick={() => setTab("orders")}>Open Orders ({orders.length})</button>
        <button className={tab === "closed" ? "on" : ""} onClick={() => setTab("closed")}>Closed</button>
        <button className={tab === "trades" ? "on" : ""} onClick={() => setTab("trades")}>Market Trades</button>
        {/* Dev: charge one 8h funding interval now instead of waiting — longs pay shorts. */}
        <button className="mgt-hbtn" style={{ marginLeft: "auto" }} title="Dev: charge one funding interval now"
                onClick={() => { void api.futuresApplyFunding().then(onDone).catch(() => {}); }}>Charge funding (dev)</button>
      </div>
      {err && <p className="mgt-err">{err}</p>}
      {tab === "orders" && (
        <div className="oo-table">
          <div className="fut-h"><span>Symbol</span><span>Type</span><span className="num">Side</span><span className="num">Size</span><span className="num">Price / Trigger</span><span></span></div>
          {orders.length === 0 && <p className="tp-empty">No open orders.</p>}
          {orders.map((o) => (
            <div className="fut-r" key={o.id}>
              <span><b>{o.symbol}</b></span>
              <span className="mono">{o.order_type}{o.reduce_only && <em title="Closes the position (reduce-only)"> · reduce</em>}</span>
              <span className={`num fut-side ${o.side.toLowerCase()}`}>{o.side}</span>
              <span className="num mono">{trimAmount(o.size)}</span>
              <span className="num mono">{Number(o.price).toFixed(2)}</span>
              <span className="num fut-actions"><button className="cancel" onClick={() => run(() => api.futuresCancelOrder(o.id))}>Cancel</button></span>
            </div>
          ))}
        </div>
      )}
      {tab === "pos" && (
      <div className="oo-table">
        <div className="fut-h"><span>Symbol</span><span>Size</span><span className="num">Entry</span><span className="num">Mark</span><span className="num">Liq. Price</span><span className="num">PnL (ROE)</span><span></span></div>
        {positions.length === 0 && <p className="tp-empty">No open positions.</p>}
        {positions.map((p) => {
          const pnl = Number(p.unrealized_pnl ?? 0);
          const editing = edit?.id === p.id;
          return (
            <Fragment key={p.id}>
            <div className="fut-r">
              <span><b>{p.symbol}</b> <span className={`fut-side ${p.side.toLowerCase()}`} onClick={() => openEdit(p.id, "lev", trimAmount(p.leverage))} style={{ cursor: "pointer" }} title="Click to change leverage">{p.side} {trimAmount(p.leverage)}x · {p.cross ? "Cross" : "Iso"}</span></span>
              <span className="mono">{trimAmount(p.size)}</span>
              <span className="num mono">{Number(p.entry_price).toFixed(2)}</span>
              <span className="num mono" title={p.last ? `Last (fill) price ${Number(p.last).toFixed(2)} · mark drives PnL/liq` : undefined}>{p.mark ? Number(p.mark).toFixed(2) : "—"}</span>
              <span className="num mono warn">{Number(p.liquidation_price).toFixed(2)}</span>
              <span className={`num mono ${pnl >= 0 ? "up" : "down"}`}>{pnl >= 0 ? "+" : ""}{p.inverse ? `${trimAmount(p.unrealized_pnl ?? "0")} ${p.margin_asset}` : pnl.toFixed(2)} <em>({Number(p.roe ?? 0).toFixed(1)}%)</em>{Number(p.funding_accrued) !== 0 && <em title="Funding paid(-)/received(+)"> · fund {Number(p.funding_accrued) >= 0 ? "+" : ""}{Number(p.funding_accrued).toFixed(4)}</em>}</span>
              <span className="num fut-actions">
                <button className={`cancel ${editing && edit.kind === "addM" ? "on" : ""}`} title="Add margin" onClick={() => openEdit(p.id, "addM")}>+M</button>
                <button className={`cancel ${editing && edit.kind === "remM" ? "on" : ""}`} title="Remove margin" onClick={() => openEdit(p.id, "remM")}>−M</button>
                <button className={`cancel ${editing && edit.kind === "tpsl" ? "on" : ""}`} title="Set take-profit / stop-loss" onClick={() => openEdit(p.id, "tpsl")}>TP/SL</button>
                <button className="cancel" title="Close half" onClick={() => run(() => api.futuresClose(p.id, trimAmount(String(Number(p.size) / 2))))}>½</button>
                <button className="cancel" onClick={() => run(() => api.futuresClose(p.id))}>Close</button>
              </span>
            </div>
            {editing && (
              <div className="fut-edit">
                {edit.kind === "tpsl" ? (
                  <>
                    <label>Take-Profit <input autoFocus value={ev.a} onChange={(e) => setEv((s) => ({ ...s, a: num(e.target.value) }))} placeholder="price" inputMode="decimal" /></label>
                    <label>Stop-Loss <input value={ev.b} onChange={(e) => setEv((s) => ({ ...s, b: num(e.target.value) }))} placeholder="price" inputMode="decimal" /></label>
                  </>
                ) : (
                  <label>
                    {edit.kind === "lev" ? "Leverage (1–100x)" : edit.kind === "addM" ? "Add margin" : "Remove margin"}
                    <input autoFocus value={ev.a} onChange={(e) => setEv((s) => ({ ...s, a: num(e.target.value) }))}
                           onKeyDown={(e) => { if (e.key === "Enter") commitEdit(p); }} placeholder="amount" inputMode="decimal" />
                  </label>
                )}
                <button className="fut-edit-ok" onClick={() => commitEdit(p)}>Confirm</button>
                <button className="cancel" onClick={() => setEdit(null)}>Cancel</button>
              </div>
            )}
            </Fragment>
          );
        })}
      </div>
      )}
      {tab === "closed" && (
        <div className="oo-table">
          <div className="fut-h"><span>Symbol</span><span>Size</span><span className="num">Entry</span><span className="num">Realized PnL</span><span>Status</span><span className="num">Closed</span></div>
          {closed.length === 0 && <p className="tp-empty">No closed positions yet.</p>}
          {closed.map((p) => {
            const pnl = Number(p.realized_pnl);
            return (
              <div className="fut-r" key={p.id}>
                <span><b>{p.symbol}</b> <span className={`fut-side ${p.side.toLowerCase()}`}>{p.side} {trimAmount(p.leverage)}x</span></span>
                <span className="mono">{trimAmount(p.size)}</span>
                <span className="num mono">{Number(p.entry_price).toFixed(2)}</span>
                <span className={`num mono ${pnl >= 0 ? "up" : "down"}`}>{pnl >= 0 ? "+" : ""}{p.inverse ? `${trimAmount(p.realized_pnl)} ${p.margin_asset}` : pnl.toFixed(2)}</span>
                <span className={p.status === "LIQUIDATED" ? "down" : "dim"}>{p.status}</span>
                <span className="num dim">{p.closed_at ? new Date(p.closed_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</span>
              </div>
            );
          })}
        </div>
      )}
      {tab === "trades" && <RecentTrades symbol={symbol} trades={trades} />}
    </>
  );
}

function TransferModal({ asset, onClose, onDone }: { asset: string; onClose: () => void; onDone: (a: FuturesAccount) => void }) {
  const [amount, setAmount] = useState("");
  const [deposit, setDeposit] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try { onDone(await api.futuresTransfer(amount, deposit, asset)); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="mgt-modal" onClick={onClose}>
      <div className="mgt-box" onClick={(e) => e.stopPropagation()}>
        <div className="mgt-box-h"><h3>Transfer {asset}</h3><button onClick={onClose}>✕</button></div>
        <div className="mgt-seg">
          <button className={deposit ? "on" : ""} onClick={() => setDeposit(true)}>Spot → Futures</button>
          <button className={!deposit ? "on" : ""} onClick={() => setDeposit(false)}>Futures → Spot</button>
        </div>
        <div className="mgt-frow"><input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder={`Amount ${asset}`} /></div>
        {err && <p className="mgt-err">{err}</p>}
        <button className="mgt-open-btn" disabled={busy || !amount} onClick={go}>{busy ? "…" : "Transfer"}</button>
      </div>
    </div>
  );
}
