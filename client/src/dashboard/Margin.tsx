import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type MarginAccount } from "../lib/api";
import "./margin.css";

const ASSETS = ["USDT", "BTC", "ETH", "BNB"];
const PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"];

/**
 * Cross-margin console: open an account, move collateral in from spot, borrow within your leverage,
 * trade on margin (auto-borrowing any shortfall — a sell you can't cover is a short), and watch the
 * margin level. Spot funds are never touched by margin risk; the two wallets are separate.
 */
export function Margin() {
  const [account, setAccount] = useState<MarginAccount | null>(null);
  const [noAccount, setNoAccount] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      setAccount(await api.marginAccount("CROSS"));
      setNoAccount(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { setNoAccount(true); setAccount(null); }
      else setErr(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<MarginAccount>, ok: string) {
    setErr(null); setNote(null);
    try { setAccount(await fn()); setNote(ok); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }

  return (
    <div className="mgn">
      <div className="mgn-head">
        <h1>Margin <span className="mgn-tag">Cross</span></h1>
        <p className="mgn-sub">Trade with borrowed funds. Leverage amplifies gains and losses — a low margin level triggers liquidation.</p>
      </div>

      {err && <p className="mgn-err">{err}</p>}
      {note && <p className="mgn-note">{note}</p>}

      {noAccount && (
        <div className="mgn-open">
          <p>You don’t have a margin account yet.</p>
          <OpenAccount onDone={load} />
        </div>
      )}

      {account && (
        <>
          <HealthPanel a={account} />
          <div className="mgn-grid">
            <Collateral onRun={run} />
            <BorrowBox account={account} onRun={run} />
          </div>
          <Loans account={account} onRun={run} />
          <OrderBox onDone={load} onNote={setNote} onErr={setErr} />
        </>
      )}
    </div>
  );
}

function OpenAccount({ onDone }: { onDone: () => void }) {
  const [tier, setTier] = useState<"CLASSIC" | "PRO">("CLASSIC");
  const [leverage, setLeverage] = useState("3");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function open() {
    setBusy(true); setErr(null);
    try { await api.marginOpen({ mode: "CROSS", tier, leverage }); onDone(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return (
    <div className="mgn-openform">
      <label>Tier
        <select value={tier} onChange={(e) => setTier(e.target.value as "CLASSIC" | "PRO")}>
          <option value="CLASSIC">Classic (up to 3x)</option>
          <option value="PRO">Pro (up to 20x)</option>
        </select>
      </label>
      <label>Leverage<input value={leverage} onChange={(e) => setLeverage(e.target.value)} inputMode="decimal" /></label>
      <button className="mgn-primary" disabled={busy} onClick={open}>{busy ? "…" : "Open margin account"}</button>
      {err && <p className="mgn-err">{err}</p>}
    </div>
  );
}

function HealthPanel({ a }: { a: MarginAccount }) {
  const level = a.margin_level ? Number(a.margin_level) : null;
  const cls = a.health === "liquidatable" ? "bad" : a.health === "margin_call" ? "warn" : "good";
  return (
    <div className="mgn-health">
      <div className={`mgn-level ${cls}`}>
        <span className="mgn-level-label">Margin level</span>
        <span className="mgn-level-val">{level === null ? "∞" : level.toFixed(2)}</span>
        <span className="mgn-level-tag">{a.health.replace("_", " ")}</span>
      </div>
      <div className="mgn-stats">
        <Stat label="Equity" value={`$${fmt(a.equity_usd)}`} />
        <Stat label="Total assets" value={`$${fmt(a.gross_usd)}`} />
        <Stat label="Total debt" value={`$${fmt(a.debt_usd)}`} />
        <Stat label="Available to borrow" value={`$${fmt(a.max_borrow_usd)}`} />
        <Stat label="Max leverage" value={`${Number(a.max_leverage)}x`} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="mgn-stat"><span>{label}</span><b>{value}</b></div>;
}

function Collateral({ onRun }: { onRun: (fn: () => Promise<MarginAccount>, ok: string) => void }) {
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [deposit, setDeposit] = useState(true);
  return (
    <div className="mgn-card">
      <h3>Collateral</h3>
      <div className="mgn-seg">
        <button className={deposit ? "on" : ""} onClick={() => setDeposit(true)}>Spot → Margin</button>
        <button className={!deposit ? "on" : ""} onClick={() => setDeposit(false)}>Margin → Spot</button>
      </div>
      <div className="mgn-row">
        <select value={asset} onChange={(e) => setAsset(e.target.value)}>{ASSETS.map((a) => <option key={a}>{a}</option>)}</select>
        <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Amount" />
      </div>
      <button className="mgn-primary" disabled={!amount}
        onClick={() => onRun(() => api.marginTransfer({ mode: "CROSS", asset, amount, deposit }), deposit ? "Collateral added" : "Withdrawn to spot")}>
        {deposit ? "Transfer in" : "Transfer out"}
      </button>
    </div>
  );
}

function BorrowBox({ account, onRun }: { account: MarginAccount; onRun: (fn: () => Promise<MarginAccount>, ok: string) => void }) {
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("");
  return (
    <div className="mgn-card">
      <h3>Borrow</h3>
      <p className="mgn-hint">Available: ${fmt(account.max_borrow_usd)} at {Number(account.max_leverage)}x</p>
      <div className="mgn-row">
        <select value={asset} onChange={(e) => setAsset(e.target.value)}>{ASSETS.map((a) => <option key={a}>{a}</option>)}</select>
        <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Amount" />
      </div>
      <button className="mgn-primary" disabled={!amount}
        onClick={() => onRun(() => api.marginBorrow({ mode: "CROSS", asset, amount }), "Borrowed")}>
        Borrow
      </button>
    </div>
  );
}

function Loans({ account, onRun }: { account: MarginAccount; onRun: (fn: () => Promise<MarginAccount>, ok: string) => void }) {
  if (account.loans.length === 0) return null;
  return (
    <div className="mgn-loans">
      <h3>Open loans</h3>
      {account.loans.map((ln) => (
        <div className="mgn-loan" key={ln.id}>
          <span className="mono">{fmt(ln.owed)} {ln.asset}</span>
          <span className="dim">principal {fmt(ln.principal)} · interest {fmt(ln.accrued_interest)} · {(Number(ln.hourly_rate) * 100).toFixed(4)}%/h</span>
          <button className="mgn-mini" onClick={() => onRun(() => api.marginRepay({ loan_id: ln.id, amount: ln.owed }), "Loan repaid")}>Repay all</button>
        </div>
      ))}
    </div>
  );
}

function OrderBox({ onDone, onNote, onErr }: { onDone: () => void; onNote: (s: string) => void; onErr: (s: string) => void }) {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [type, setType] = useState<"LIMIT" | "MARKET">("LIMIT");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [autoBorrow, setAutoBorrow] = useState(true);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const o = await api.marginOrder({
        mode: "CROSS", symbol, side, type, quantity: qty,
        price: type === "LIMIT" ? price : null, auto_borrow: autoBorrow,
      });
      onNote(`${side} ${o.status} — filled ${fmt(o.filled_quantity)}/${fmt(o.quantity)}`);
      setQty("");
      onDone();
    } catch (e) {
      onErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="mgn-card mgn-order">
      <h3>Margin order</h3>
      <div className="mgn-row">
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>{PAIRS.map((p) => <option key={p}>{p}</option>)}</select>
        <div className="mgn-seg sm">
          <button className={side === "BUY" ? "buy on" : ""} onClick={() => setSide("BUY")}>Buy / Long</button>
          <button className={side === "SELL" ? "sell on" : ""} onClick={() => setSide("SELL")}>Sell / Short</button>
        </div>
      </div>
      <div className="mgn-row">
        <div className="mgn-seg sm">
          <button className={type === "LIMIT" ? "on" : ""} onClick={() => setType("LIMIT")}>Limit</button>
          <button className={type === "MARKET" ? "on" : ""} onClick={() => setType("MARKET")}>Market</button>
        </div>
        <input value={qty} onChange={(e) => setQty(e.target.value)} inputMode="decimal" placeholder="Quantity" />
        {type === "LIMIT" && <input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" placeholder="Price" />}
      </div>
      <label className="mgn-check">
        <input type="checkbox" checked={autoBorrow} onChange={(e) => setAutoBorrow(e.target.checked)} />
        Auto-borrow the shortfall
      </label>
      <button className={`mgn-primary ${side === "BUY" ? "buy" : "sell"}`} disabled={busy || !qty} onClick={submit}>
        {busy ? "…" : `${side === "BUY" ? "Buy / Long" : "Sell / Short"} ${symbol.replace("USDT", "")}`}
      </button>
    </div>
  );
}

function fmt(v: string) {
  const n = Number(v);
  return n.toLocaleString(undefined, { maximumFractionDigits: n >= 1 ? 2 : 6 });
}
