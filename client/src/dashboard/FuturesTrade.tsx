import { useCallback, useEffect, useState } from "react";
import { api, ApiError, trimAmount, type FuturesAccount, type MarketInfo } from "../lib/api";
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

  return (
    <div className="trade">
      {xfer && <TransferModal asset={inverse ? base : "USDT"} onClose={() => setXfer(false)} onDone={(a) => { setAcct(a); setXfer(false); }} />}
      <div className="term-grid mgt">
        <div className="g-ticker tk-bar">
          <div className="tk-symbol">
            <span className="tk-name">{base}<span className="tk-quote">{inverse ? "USD" : "/USDT"}</span></span>
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
          <div className="mgt-ml"><span>Futures Balance</span><b>{acct ? (inverse ? `${trimAmount(String(coinBal))} ${base}` : `${usdtBal.toFixed(2)} USDT`) : "—"}</b></div>
          <button className="mgt-hbtn" onClick={() => setXfer(true)}>Transfer</button>
        </div>

        <aside className="g-left">
          {tradeable ? (
            <><OrderBookPanel book={book} onPick={setClickedPrice} live={ticker?.price ?? null} /><RecentTrades symbol={symbol} trades={trades} /></>
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
                         livePrice={ticker?.price ?? null} onDone={loadAcct} />}
        </section>

        <aside className="g-market"><MarketList current={symbol} onPick={setSymbol} /></aside>

        <section className="g-orders tp">
          <Positions acct={acct} onDone={loadAcct} />
        </section>
      </div>
    </div>
  );
}

function FuturesForm({ symbol, inverse, balance, livePrice, onDone }: { symbol: string; inverse: boolean; balance: number; livePrice: number | null; onDone: () => void }) {
  const [lev, setLev] = useState("10");
  const [pct, setPct] = useState(0);
  const [busy, setBusy] = useState<"LONG" | "SHORT" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const base = symbol.replace(/USDT$/, "");
  const price = livePrice ?? 0;
  const leverage = Number(lev) || 1;
  // COIN-M: balance is in coin; size = USD notional, margin in coin. USDT-M: size = base qty, margin USDT.
  const marginUnit = inverse ? base : "USDT";
  const sizeUnit = inverse ? "USD" : base;
  const maxNotionalUsd = price > 0 ? balance * (inverse ? price : 1) * leverage : 0; // balance*price for coin, balance for USDT
  const notionalUsd = (maxNotionalUsd * pct) / 100;
  const size = inverse ? notionalUsd : (price > 0 ? notionalUsd / price : 0); // inverse: size IS the USD notional
  const sizeStr = size > 0 ? String(Number(size.toFixed(inverse ? 2 : 6))) : "";
  const margin = price > 0 && size > 0 ? (inverse ? (size / price) / leverage : (size * price) / leverage) : 0;

  async function submit(side: "LONG" | "SHORT") {
    if (size <= 0) { setNote("choose a size with the slider"); return; }
    setBusy(side); setNote("");
    try {
      const o = await api.futuresOrder({ symbol, side, size: sizeStr, leverage: lev, inverse });
      setNote(`${side} opened @ ${trimAmount(o.entry_price)} · margin ${trimAmount(o.margin)} ${o.margin_asset}`);
      setPct(0); onDone();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(null); }
  }

  return (
    <div className="fut-form">
      <div className="fut-lev">
        <label>Leverage</label>
        <div className="fut-lev-row">
          <input type="range" min={1} max={100} value={lev} onChange={(e) => setLev(e.target.value)} />
          <span className="fut-lev-val">{lev}x</span>
        </div>
      </div>
      <div className="of-field"><label>Size ({sizeUnit})</label>
        <div className="of-input readonly"><input value={sizeStr} readOnly placeholder="0" /><span className="of-unit">{sizeUnit}</span></div>
      </div>
      <div className="of-slider">
        <input type="range" min={0} max={100} step={1} value={pct} onChange={(e) => setPct(Number(e.target.value))} />
        <div className="of-pcts">{[0, 25, 50, 75, 100].map((p) => <button key={p} className={pct === p ? "on" : ""} onClick={() => setPct(p)}>{p}%</button>)}</div>
      </div>
      <div className="of-row"><span>Avbl</span><span className="mono">{inverse ? `${trimAmount(String(balance))} ${base}` : `${balance.toFixed(2)} USDT`}</span></div>
      <div className="of-row"><span>Margin</span><span className="mono">{margin > 0 ? `${inverse ? trimAmount(String(Number(margin.toFixed(8)))) : margin.toFixed(2)} ${marginUnit}` : "—"}</span></div>
      <div className="fut-btns">
        <button className="fut-long" disabled={busy !== null} onClick={() => submit("LONG")}>{busy === "LONG" ? "…" : "Buy / Long"}</button>
        <button className="fut-short" disabled={busy !== null} onClick={() => submit("SHORT")}>{busy === "SHORT" ? "…" : "Sell / Short"}</button>
      </div>
      {note && <p className="of-note">{note}</p>}
    </div>
  );
}

function Positions({ acct, onDone }: { acct: FuturesAccount | null; onDone: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  async function close(id: number) {
    setErr(null);
    try { await api.futuresClose(id); onDone(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }
  const positions = acct?.positions ?? [];
  return (
    <>
      <div className="oo-tabs"><button className="on">Positions ({positions.length})</button></div>
      {err && <p className="mgt-err">{err}</p>}
      <div className="oo-table">
        <div className="fut-h"><span>Symbol</span><span>Size</span><span className="num">Entry</span><span className="num">Mark</span><span className="num">Liq. Price</span><span className="num">PnL (ROE)</span><span></span></div>
        {positions.length === 0 && <p className="tp-empty">No open positions.</p>}
        {positions.map((p) => {
          const pnl = Number(p.unrealized_pnl ?? 0);
          return (
            <div className="fut-r" key={p.id}>
              <span><b>{p.symbol}</b> <span className={`fut-side ${p.side.toLowerCase()}`}>{p.side} {trimAmount(p.leverage)}x</span></span>
              <span className="mono">{trimAmount(p.size)}</span>
              <span className="num mono">{Number(p.entry_price).toFixed(2)}</span>
              <span className="num mono">{p.mark ? Number(p.mark).toFixed(2) : "—"}</span>
              <span className="num mono warn">{Number(p.liquidation_price).toFixed(2)}</span>
              <span className={`num mono ${pnl >= 0 ? "up" : "down"}`}>{pnl >= 0 ? "+" : ""}{p.inverse ? `${trimAmount(p.unrealized_pnl ?? "0")} ${p.margin_asset}` : pnl.toFixed(2)} <em>({Number(p.roe ?? 0).toFixed(1)}%)</em></span>
              <span className="num"><button className="cancel" onClick={() => close(p.id)}>Close</button></span>
            </div>
          );
        })}
      </div>
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
