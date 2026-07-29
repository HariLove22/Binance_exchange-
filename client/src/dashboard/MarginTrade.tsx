import { useCallback, useEffect, useState } from "react";
import { api, ApiError, trimAmount, type MarginAccount, type MarketInfo } from "../lib/api";
import { useTicker } from "../lib/useLive";
import { useMarketWs } from "../lib/marketWs";
import { TradeChart } from "./TradeChart";
import { OrderBookPanel, RecentTrades, MarketList, fmtPx, INTERVALS } from "./Trade";
import "./trade.css";
import "./margin-term.css";

type Mode = "CROSS" | "ISOLATED";

/**
 * Margin trading terminal — the spot terminal plus leverage. Same order book, chart, and market
 * list; a margin order form that trades from the margin wallet with Normal/Borrow modes, a live
 * margin-level (ML) readout, and Transfer / Borrow-Repay actions. Cross shares one collateral pool;
 * isolated rings a single pair.
 */
export function MarginTrade() {
  const [markets, setMarkets] = useState<MarketInfo[]>([]);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("1m");
  const [mode, setMode] = useState<Mode>("CROSS");
  const [account, setAccount] = useState<MarginAccount | null>(null);
  const [noAccount, setNoAccount] = useState(false);
  const [clickedPrice, setClickedPrice] = useState<string | null>(null);
  const [modal, setModal] = useState<null | "transfer" | "borrow">(null);

  const loadMarkets = useCallback(() => api.marketSymbols().then(setMarkets).catch(() => {}), []);
  const loadAccount = useCallback(async () => {
    try {
      setAccount(await api.marginAccount(mode, mode === "ISOLATED" ? symbol : undefined));
      setNoAccount(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { setNoAccount(true); setAccount(null); }
    }
  }, [mode, symbol]);

  useEffect(() => { loadMarkets(); }, [loadMarkets]);
  useEffect(() => { loadAccount(); }, [loadAccount]);
  useEffect(() => {
    const h = () => loadAccount();
    window.addEventListener("orders-changed", h);
    return () => window.removeEventListener("orders-changed", h);
  }, [loadAccount]);

  const market = markets.find((m) => m.symbol === symbol);
  const tradeable = market !== undefined;
  const ticker = useTicker(symbol);
  const up = (ticker?.changePercent ?? 0) >= 0;
  const { book, trades } = useMarketWs(tradeable ? symbol : null);

  const level = account?.margin_level ? Number(account.margin_level) : null;
  const hourlyRate = account?.loans[0]?.hourly_rate ?? "0.000125";

  return (
    <div className="trade">
      {modal === "transfer" && account && <TransferModal account={account} onClose={() => setModal(null)} onDone={() => { setModal(null); loadAccount(); }} />}
      {modal === "borrow" && account && <BorrowRepayModal account={account} onClose={() => setModal(null)} onDone={() => { setModal(null); loadAccount(); }} />}

      <div className="term-grid mgt">
        {/* ticker bar with margin extras */}
        <div className="g-ticker tk-bar">
          <div className="tk-symbol">
            <span className="tk-name">{symbol.replace(/USDT$/, "")}<span className="tk-quote">/USDT</span></span>
            <span className="mgt-lev">{account ? `${Number(account.max_leverage)}x` : "—"}</span>
          </div>
          {ticker ? (
            <>
              <span className={`tk-price ${up ? "bid" : "ask"}`}>{fmtPx(ticker.price)}</span>
              <div className="tk-stats">
                <span className={`tk-chg ${up ? "bid" : "ask"}`}>{up ? "+" : ""}{ticker.changePercent.toFixed(2)}%</span>
                <span className="tk-s"><i>24h High</i>{fmtPx(ticker.high)}</span>
                <span className="tk-s"><i>24h Low</i>{fmtPx(ticker.low)}</span>
                <span className="tk-s"><i>Hourly Interest</i>{(Number(hourlyRate) * 100).toFixed(5)}%</span>
              </div>
            </>
          ) : <span className="tk-loading">connecting to live feed…</span>}
          <div className="tk-spacer" />
          <div className="mgt-ml">
            <span>Margin Level</span>
            <b className={account?.health ?? ""}>{level === null ? "999.00" : level.toFixed(2)}</b>
          </div>
          <button className="mgt-hbtn" onClick={() => setModal("borrow")} disabled={!account}>Borrow / Repay</button>
          <button className="mgt-hbtn" onClick={() => setModal("transfer")} disabled={!account}>Transfer</button>
        </div>

        {/* left: order book + trades */}
        <aside className="g-left">
          {tradeable ? (
            <>
              <OrderBookPanel book={book} onPick={setClickedPrice} live={ticker?.price ?? null} />
              <RecentTrades symbol={symbol} trades={trades} />
            </>
          ) : <div className="tp fill"><div className="tp-head"><span className="tp-title">Order book</span></div><p className="tp-empty">List this pair on Spot first.</p></div>}
        </aside>

        {/* chart */}
        <section className="g-chart tp">
          <div className="tp-head">
            <span className="tp-title">{symbol}</span>
            <div className="ivals">{INTERVALS.map((i) => <button key={i} className={interval === i ? "on" : ""} onClick={() => setInterval(i)}>{i}</button>)}</div>
          </div>
          <TradeChart symbol={symbol} interval={interval} />
        </section>

        {/* margin order form */}
        <section className="g-form tp">
          <div className="mgt-modes">
            {(["CROSS", "ISOLATED"] as Mode[]).map((m) => (
              <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{m === "CROSS" ? "Cross" : "Isolated"}</button>
            ))}
            <span className="mgt-steps">Steps: Transfer → Borrow/Trade → Repay</span>
          </div>
          {noAccount ? (
            <div className="mgt-open">
              <p>No {mode.toLowerCase()} margin account for this {mode === "ISOLATED" ? "pair" : ""}.</p>
              <OpenInline mode={mode} symbol={symbol} onDone={loadAccount} />
            </div>
          ) : account ? (
            <MarginOrderForm account={account} market={market} symbol={symbol} livePrice={ticker?.price ?? null}
                             clickedPrice={clickedPrice} onDone={loadAccount} />
          ) : <p className="tp-empty">loading margin account…</p>}
        </section>

        {/* market list */}
        <aside className="g-market"><MarketList current={symbol} onPick={setSymbol} /></aside>

        {/* bottom: orders / holdings / loans */}
        <section className="g-orders tp">
          <MarginBottom account={account} onDone={loadAccount} />
        </section>
      </div>
    </div>
  );
}

function OpenInline({ mode, symbol, onDone }: { mode: Mode; symbol: string; onDone: () => void }) {
  const [lev, setLev] = useState(mode === "CROSS" ? "3" : "5");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function open() {
    setBusy(true); setErr(null);
    try {
      if (mode === "CROSS") await api.marginOpen({ mode: "CROSS", tier: "PRO", leverage: lev });
      else await api.marginOpen({ mode: "ISOLATED", symbol, tier: "PRO", leverage: lev });
      onDone();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="mgt-open-row">
      <label>Leverage<input value={lev} onChange={(e) => setLev(e.target.value)} inputMode="decimal" /></label>
      <button className="mgt-open-btn" disabled={busy} onClick={open}>{busy ? "…" : `Open ${mode === "CROSS" ? "Cross" : "Isolated " + symbol}`}</button>
      {err && <p className="mgt-err">{err}</p>}
    </div>
  );
}

function MarginOrderForm({ account, market, symbol, livePrice, clickedPrice, onDone }: {
  account: MarginAccount; market?: MarketInfo; symbol: string; livePrice: number | null; clickedPrice: string | null; onDone: () => void;
}) {
  const [type, setType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [price, setPrice] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const base = symbol.replace(/USDT$/, "");

  useEffect(() => { if (clickedPrice) setPrice(clickedPrice); }, [clickedPrice]);
  useEffect(() => { setPrice((p) => (p === "" && livePrice ? livePrice.toFixed(2) : p)); }, [livePrice]);

  const bal = (a: string) => Number(account.balances.find((b) => b.asset === a)?.available ?? "0");
  const maxBorrowUsd = Number(account.max_borrow_usd);

  return (
    <>
      <div className="of-tabs">
        {(["LIMIT", "MARKET"] as const).map((t) => (
          <button key={t} className={type === t ? "on" : ""} onClick={() => setType(t)}>{t === "LIMIT" ? "Limit" : "Market"}</button>
        ))}
        <span className="of-tab-note">margin · {Number(account.max_leverage)}x · auto-borrow the shortfall</span>
      </div>
      <div className="of-cols">
        <MarginSide side="BUY" type={type} symbol={symbol} base={base} market={market} price={price} setPrice={setPrice}
                    livePrice={livePrice} quoteAvail={bal("USDT")} baseAvail={bal(base)} maxBorrowUsd={maxBorrowUsd}
                    mode={account.mode} onNote={setNote} onDone={onDone} />
        <MarginSide side="SELL" type={type} symbol={symbol} base={base} market={market} price={price} setPrice={setPrice}
                    livePrice={livePrice} quoteAvail={bal("USDT")} baseAvail={bal(base)} maxBorrowUsd={maxBorrowUsd}
                    mode={account.mode} onNote={setNote} onDone={onDone} />
      </div>
      {note && <p className="of-note">{note}</p>}
    </>
  );
}

function MarginSide({ side, type, symbol, base, market, price, setPrice, livePrice, quoteAvail, baseAvail, maxBorrowUsd, mode, onNote, onDone }: {
  side: "BUY" | "SELL"; type: "LIMIT" | "MARKET"; symbol: string; base: string; market?: MarketInfo;
  price: string; setPrice: (p: string) => void; livePrice: number | null;
  quoteAvail: number; baseAvail: number; maxBorrowUsd: number; mode: string;
  onNote: (n: string) => void; onDone: () => void;
}) {
  const [borrow, setBorrow] = useState(true);
  const [pct, setPct] = useState(0);
  const [busy, setBusy] = useState(false);
  const step = Number(market?.qty_step ?? "0.0001");
  const refPrice = type === "LIMIT" && price ? Number(price) : livePrice ?? 0;

  // With borrow on, buying power includes the leverage headroom; without, only what's in the wallet.
  const buyPower = borrow ? quoteAvail + maxBorrowUsd : quoteAvail;
  const sellPower = borrow ? baseAvail + (refPrice > 0 ? maxBorrowUsd / refPrice : 0) : baseAvail;
  const maxQty = side === "BUY" ? (refPrice > 0 ? buyPower / refPrice : 0) : sellPower;
  const qty = maxQty > 0 ? Math.floor((maxQty * (pct / 100)) / step) * step : 0;
  const qtyStr = qty > 0 ? String(Number(qty.toFixed(8))) : "";
  const total = refPrice > 0 && qty > 0 ? refPrice * qty : 0;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (qty <= 0) { onNote("choose an amount with the slider"); return; }
    setBusy(true); onNote("");
    try {
      const o = await api.marginOrder({
        mode: mode as "CROSS" | "ISOLATED", symbol, side, type, quantity: qtyStr,
        price: type === "LIMIT" ? price : null, auto_borrow: borrow,
      });
      onNote(`${side} ${o.status} — filled ${trimAmount(o.filled_quantity)}/${trimAmount(o.quantity)} ${base}${o.wallet ? ` · ${o.wallet}` : ""}`);
      setPct(0); onDone();
      window.dispatchEvent(new CustomEvent("orders-changed"));
      window.dispatchEvent(new CustomEvent("book-changed"));
    } catch (err) {
      onNote(err instanceof ApiError ? err.message : String(err));
    } finally { setBusy(false); }
  }

  return (
    <form className="of-col" onSubmit={submit}>
      <div className="mgt-nb">
        <button type="button" className={borrow ? "" : "on"} onClick={() => setBorrow(false)}>Normal</button>
        <button type="button" className={borrow ? "on" : ""} onClick={() => setBorrow(true)}>Borrow</button>
      </div>
      <div className="of-field">
        <label>Price</label>
        {type === "MARKET" ? <div className="of-market-px">Market</div> : (
          <div className="of-input"><input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" /><span className="of-unit">USDT</span></div>
        )}
      </div>
      <div className="of-field">
        <label>Amount</label>
        <div className="of-input readonly"><input value={qtyStr} readOnly placeholder="0" /><span className="of-unit">{base}</span></div>
      </div>
      <div className="of-slider">
        <input type="range" min={0} max={100} step={1} value={pct} onChange={(e) => setPct(Number(e.target.value))} className={side.toLowerCase()} />
        <div className="of-pcts">{[0, 25, 50, 75, 100].map((p) => <button type="button" key={p} className={pct === p ? "on" : ""} onClick={() => setPct(p)}>{p}%</button>)}</div>
      </div>
      <div className="of-row"><span>Avbl</span><span className="mono">{side === "BUY" ? `${quoteAvail.toFixed(2)} USDT` : `${trimAmount(baseAvail.toString())} ${base}`}</span></div>
      <div className="of-row"><span>Max {borrow ? "(with borrow)" : ""}</span><span className="mono">{trimAmount(maxQty.toFixed(8))} {base}</span></div>
      <div className="of-row"><span>Total</span><span className="mono">{total > 0 ? `${total.toFixed(2)} USDT` : `Min ${trimAmount(market?.min_notional ?? "5")} USDT`}</span></div>
      <button className={`of-submit ${side.toLowerCase()}`} disabled={busy}>{busy ? "…" : `${side === "BUY" ? "Buy / Long" : "Sell / Short"} ${base}`}</button>
    </form>
  );
}

function MarginBottom({ account, onDone }: { account: MarginAccount | null; onDone: () => void }) {
  const [tab, setTab] = useState<"holdings" | "loans">("holdings");
  const [err, setErr] = useState<string | null>(null);
  if (!account) return <><div className="tp-head"><span className="tp-title">Holdings</span></div><p className="tp-empty">—</p></>;

  async function repay(id: number, amount: string) {
    setErr(null);
    try { await api.marginRepay({ loan_id: id, amount }); onDone(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }

  return (
    <>
      <div className="oo-tabs">
        <button className={tab === "holdings" ? "on" : ""} onClick={() => setTab("holdings")}>Holdings</button>
        <button className={tab === "loans" ? "on" : ""} onClick={() => setTab("loans")}>Loans ({account.loans.length})</button>
        <span className="mgt-eq">Equity ${Number(account.equity_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })} · Debt ${Number(account.debt_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
      </div>
      {err && <p className="mgt-err">{err}</p>}
      {tab === "holdings" ? (
        <div className="oo-table">
          <div className="oo-h5"><span>Asset</span><span className="num">Available</span><span className="num">Locked</span><span></span><span></span></div>
          {account.balances.length === 0 && <p className="tp-empty">No margin balances. Transfer collateral to begin.</p>}
          {account.balances.map((b) => (
            <div className="oo-r5" key={b.asset}>
              <span className="mono">{b.asset}</span>
              <span className="num">{trimAmount(b.available)}</span>
              <span className="num dim">{trimAmount(b.locked)}</span>
              <span></span><span></span>
            </div>
          ))}
        </div>
      ) : (
        <div className="oo-table">
          <div className="oo-h5"><span>Asset</span><span className="num">Principal</span><span className="num">Interest</span><span className="num">Owed</span><span></span></div>
          {account.loans.length === 0 && <p className="tp-empty">No open loans.</p>}
          {account.loans.map((l) => (
            <div className="oo-r5" key={l.id}>
              <span className="mono">{l.asset}</span>
              <span className="num">{trimAmount(l.principal)}</span>
              <span className="num dim">{trimAmount(l.accrued_interest)}</span>
              <span className="num">{trimAmount(l.owed)}</span>
              <span className="num"><button className="cancel" onClick={() => repay(l.id, l.owed)}>Repay</button></span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function TransferModal({ account, onClose, onDone }: { account: MarginAccount; onClose: () => void; onDone: () => void }) {
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [deposit, setDeposit] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try {
      await api.marginTransfer({ mode: account.mode, symbol: account.symbol, asset, amount, deposit });
      onDone();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="mgt-modal" onClick={onClose}>
      <div className="mgt-box" onClick={(e) => e.stopPropagation()}>
        <div className="mgt-box-h"><h3>Transfer collateral</h3><button onClick={onClose}>✕</button></div>
        <div className="mgt-seg">
          <button className={deposit ? "on" : ""} onClick={() => setDeposit(true)}>Spot → Margin</button>
          <button className={!deposit ? "on" : ""} onClick={() => setDeposit(false)}>Margin → Spot</button>
        </div>
        <div className="mgt-frow">
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>{["USDT", "BTC", "ETH", "BNB"].map((a) => <option key={a}>{a}</option>)}</select>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Amount" />
        </div>
        {err && <p className="mgt-err">{err}</p>}
        <button className="mgt-open-btn" disabled={busy || !amount} onClick={go}>{busy ? "…" : "Transfer"}</button>
      </div>
    </div>
  );
}

function BorrowRepayModal({ account, onClose, onDone }: { account: MarginAccount; onClose: () => void; onDone: () => void }) {
  const [tab, setTab] = useState<"borrow" | "repay">("borrow");
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function go() {
    setBusy(true); setErr(null);
    try {
      if (tab === "borrow") await api.marginBorrow({ mode: account.mode, symbol: account.symbol, asset, amount });
      else {
        const loan = account.loans.find((l) => l.asset === asset);
        if (!loan) throw new Error(`no ${asset} loan to repay`);
        await api.marginRepay({ loan_id: loan.id, amount });
      }
      onDone();
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="mgt-modal" onClick={onClose}>
      <div className="mgt-box" onClick={(e) => e.stopPropagation()}>
        <div className="mgt-box-h"><h3>Borrow / Repay</h3><button onClick={onClose}>✕</button></div>
        <div className="mgt-seg">
          <button className={tab === "borrow" ? "on" : ""} onClick={() => setTab("borrow")}>Borrow</button>
          <button className={tab === "repay" ? "on" : ""} onClick={() => setTab("repay")}>Repay</button>
        </div>
        <p className="mgt-hint">{tab === "borrow" ? `Available: $${Number(account.max_borrow_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "Repay principal + interest"}</p>
        <div className="mgt-frow">
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>{["USDT", "BTC", "ETH", "BNB"].map((a) => <option key={a}>{a}</option>)}</select>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Amount" />
        </div>
        {err && <p className="mgt-err">{err}</p>}
        <button className="mgt-open-btn" disabled={busy || !amount} onClick={go}>{busy ? "…" : tab === "borrow" ? "Borrow" : "Repay"}</button>
      </div>
    </div>
  );
}
