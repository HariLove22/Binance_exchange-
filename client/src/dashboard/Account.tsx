import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type AccountOverview, type DemoAccount } from "../lib/api";
import { navigate } from "../router";
import "./accounts.css";

const DEMO_COINS = ["BTC", "ETH", "BNB", "SOL", "XRP"];

/**
 * Account center — the hub of a user's trading accounts, like Binance's wallet overview. Shows each
 * account type (Spot, Cross Margin, Isolated Margin, Demo) with its value/status and the action to
 * open, manage, or create it. Demo is a risk-free paper account with virtual funds.
 */
export function Account() {
  const [ov, setOv] = useState<AccountOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setErr(null);
    try { setOv(await api.accountOverview()); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const total = ov ? Number(ov.spot_usd) + (ov.margin.open ? Number(ov.margin.equity_usd) : 0) : 0;

  return (
    <div className="accs">
      {adding && <AddAccountModal ov={ov} onClose={() => setAdding(false)} onDone={() => { setAdding(false); load(); }} />}
      <div className="accs-head">
        <div>
          <h1>Accounts</h1>
          <p className="accs-sub">Your trading accounts and their estimated value.</p>
        </div>
        <div className="accs-head-right">
          <button className="accs-add" onClick={() => setAdding(true)}>+ Add account</button>
          <div className="accs-total">
            <span>Estimated total (real)</span>
            <b>${total.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
          </div>
        </div>
      </div>

      {err && <p className="accs-err">{err}</p>}

      <div className="accs-grid">
        {/* Spot */}
        <div className="acc-card">
          <div className="acc-top"><span className="acc-icon spot">◈</span><h3>Spot Account</h3></div>
          <p className="acc-desc">Trade and hold crypto with your own funds.</p>
          <div className="acc-val">${ov ? Number(ov.spot_usd).toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</div>
          <div className="acc-actions">
            <button className="acc-btn" onClick={() => navigate("/dashboard/assets")}>Assets</button>
            <button className="acc-btn primary" onClick={() => navigate("/dashboard/trade")}>Trade</button>
          </div>
        </div>

        {/* Cross Margin */}
        <div className="acc-card">
          <div className="acc-top"><span className="acc-icon margin">⇄</span><h3>Cross Margin</h3></div>
          <p className="acc-desc">Trade with leverage from a shared collateral pool.</p>
          {ov?.margin.open ? (
            <>
              <div className="acc-val">${Number(ov.margin.equity_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })} <span className="acc-val-sub">equity</span></div>
              <div className={`acc-health ${ov.margin.health}`}>
                {ov.margin.margin_level ? `Margin level ${Number(ov.margin.margin_level).toFixed(2)}` : "No debt"} · {ov.margin.max_leverage}x
              </div>
              <div className="acc-actions"><button className="acc-btn primary" onClick={() => navigate("/dashboard/margin")}>Manage</button></div>
            </>
          ) : (
            <>
              <div className="acc-val muted">Not opened</div>
              <div className="acc-actions"><button className="acc-btn primary" onClick={() => navigate("/dashboard/margin")}>Open margin</button></div>
            </>
          )}
        </div>

        {/* Isolated Margin */}
        <div className="acc-card">
          <div className="acc-top"><span className="acc-icon iso">◫</span><h3>Isolated Margin</h3></div>
          <p className="acc-desc">Ring-fence collateral and risk per trading pair.</p>
          <div className="acc-val muted">Per-pair</div>
          <div className="acc-actions"><button className="acc-btn" onClick={() => navigate("/dashboard/margin")}>Open per pair</button></div>
        </div>

        {/* Demo */}
        <DemoCard exists={ov?.demo.exists ?? false} totalUsd={ov?.demo.total_usd} onChange={load} />
      </div>
    </div>
  );
}

type AcctOption = {
  key: string; title: string; icon: string; iconClass: string;
  leverage: string; minDeposit: string; interest: string; collateral: string; fees: string; note: string;
  kind: "cross-classic" | "cross-pro" | "isolated" | "demo";
};

const ACCOUNT_OPTIONS: AcctOption[] = [
  {
    key: "cross-classic", title: "Cross Margin — Classic", icon: "⇄", iconClass: "margin",
    leverage: "Up to 3x", minDeposit: "$10 equivalent", interest: "≈0.30% / day (accrued hourly)",
    collateral: "Any supported asset · shared pool", fees: "0.10% maker / taker",
    note: "One margin level across all pairs. Best for getting started.", kind: "cross-classic",
  },
  {
    key: "cross-pro", title: "Cross Margin — Pro", icon: "⚡", iconClass: "pro",
    leverage: "Up to 20x", minDeposit: "$100 equivalent", interest: "≈0.30% / day (accrued hourly)",
    collateral: "Any supported asset · shared pool", fees: "0.10% maker / taker",
    note: "Higher leverage for experienced traders. You choose the leverage.", kind: "cross-pro",
  },
  {
    key: "isolated", title: "Isolated Margin", icon: "◫", iconClass: "iso",
    leverage: "Up to 10x (per pair)", minDeposit: "$10 equivalent", interest: "≈0.30% / day (accrued hourly)",
    collateral: "Ring-fenced to one pair", fees: "0.10% maker / taker",
    note: "Losses are limited to a single pair's collateral. Pick a pair.", kind: "isolated",
  },
  {
    key: "demo", title: "Demo Trading", icon: "🎮", iconClass: "demo",
    leverage: "N/A (spot practice)", minDeposit: "Free · $10,000 virtual", interest: "None",
    collateral: "Virtual funds only", fees: "0.10% simulated",
    note: "Risk-free paper trading at live prices. Nothing real is ever touched.", kind: "demo",
  },
];

const ISO_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"];

function AddAccountModal({ ov, onClose, onDone }: { ov: AccountOverview | null; onClose: () => void; onDone: () => void }) {
  const [picked, setPicked] = useState<AcctOption | null>(null);
  const [leverage, setLeverage] = useState("5");
  const [pair, setPair] = useState(ISO_PAIRS[0]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const crossOpen = ov?.margin.open ?? false;
  const demoExists = ov?.demo.exists ?? false;

  function disabledReason(o: AcctOption): string | null {
    if ((o.kind === "cross-classic" || o.kind === "cross-pro") && crossOpen) return "Cross account already open";
    if (o.kind === "demo" && demoExists) return "Demo account already created";
    return null;
  }

  async function create(o: AcctOption) {
    setBusy(true); setErr(null);
    try {
      if (o.kind === "demo") await api.demoCreate();
      else if (o.kind === "cross-classic") await api.marginOpen({ mode: "CROSS", tier: "CLASSIC", leverage: "3" });
      else if (o.kind === "cross-pro") await api.marginOpen({ mode: "CROSS", tier: "PRO", leverage });
      else await api.marginOpen({ mode: "ISOLATED", symbol: pair, tier: "PRO", leverage });
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="aa-modal" onClick={onClose}>
      <div className="aa-box" onClick={(e) => e.stopPropagation()}>
        <div className="aa-head">
          <h2>Add a trading account</h2>
          <button className="aa-x" onClick={onClose}>✕</button>
        </div>
        <p className="aa-sub">Choose an account type. Each has its own leverage, funding, and risk profile.</p>

        <div className="aa-grid">
          {ACCOUNT_OPTIONS.map((o) => {
            const reason = disabledReason(o);
            const active = picked?.key === o.key;
            return (
              <div key={o.key} className={`aa-card ${active ? "active" : ""} ${reason ? "disabled" : ""}`}
                   onClick={() => !reason && setPicked(o)}>
                <div className="aa-card-top">
                  <span className={`acc-icon ${o.iconClass}`}>{o.icon}</span>
                  <h3>{o.title}</h3>
                </div>
                <ul className="aa-details">
                  <li><span>Leverage</span><b>{o.leverage}</b></li>
                  <li><span>Min deposit</span><b>{o.minDeposit}</b></li>
                  <li><span>Interest</span><b>{o.interest}</b></li>
                  <li><span>Collateral</span><b>{o.collateral}</b></li>
                  <li><span>Trading fee</span><b>{o.fees}</b></li>
                </ul>
                <p className="aa-note">{o.note}</p>
                {reason && <div className="aa-reason">{reason}</div>}
              </div>
            );
          })}
        </div>

        {picked && !disabledReason(picked) && (
          <div className="aa-config">
            {picked.kind === "cross-pro" && (
              <label>Leverage (1–20x)
                <input value={leverage} onChange={(e) => setLeverage(e.target.value)} inputMode="decimal" />
              </label>
            )}
            {picked.kind === "isolated" && (
              <>
                <label>Pair
                  <select value={pair} onChange={(e) => setPair(e.target.value)}>{ISO_PAIRS.map((p) => <option key={p}>{p}</option>)}</select>
                </label>
                <label>Leverage (1–10x)
                  <input value={leverage} onChange={(e) => setLeverage(e.target.value)} inputMode="decimal" />
                </label>
              </>
            )}
            {err && <p className="accs-err">{err}</p>}
            <button className="acc-btn primary aa-create" disabled={busy} onClick={() => create(picked)}>
              {busy ? "…" : `Create ${picked.title}`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function DemoCard({ exists, totalUsd, onChange }: { exists: boolean; totalUsd?: string; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [demo, setDemo] = useState<DemoAccount | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadDemo = useCallback(async () => {
    try { setDemo(await api.demoGet()); } catch { /* ignore */ }
  }, []);
  useEffect(() => { if (exists && open) loadDemo(); }, [exists, open, loadDemo]);

  async function run(fn: () => Promise<DemoAccount>, msg?: string) {
    setBusy(true); setErr(null);
    try { setDemo(await fn()); onChange(); if (msg) { /* noop */ } }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="acc-card demo">
      <div className="acc-top"><span className="acc-icon demo">🎮</span><h3>Demo Trading</h3><span className="acc-tag">Practice</span></div>
      <p className="acc-desc">Risk-free paper trading with virtual funds at live prices.</p>
      {exists ? (
        <>
          <div className="acc-val">${totalUsd ? Number(totalUsd).toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"} <span className="acc-val-sub">virtual</span></div>
          <div className="acc-actions">
            <button className="acc-btn" onClick={() => setOpen((o) => !o)}>{open ? "Hide" : "Trade"}</button>
            <button className="acc-btn" disabled={busy} onClick={() => run(() => api.demoReset())}>Reset funds</button>
          </div>
        </>
      ) : (
        <>
          <div className="acc-val muted">Not created</div>
          <div className="acc-actions">
            <button className="acc-btn primary" disabled={busy} onClick={() => run(() => api.demoCreate())}>Create demo account</button>
          </div>
        </>
      )}
      {err && <p className="accs-err">{err}</p>}
      {exists && open && demo && <DemoPanel demo={demo} onTraded={(d) => { setDemo(d); onChange(); }} />}
    </div>
  );
}

function DemoPanel({ demo, onTraded }: { demo: DemoAccount; onTraded: (d: DemoAccount) => void }) {
  const [base, setBase] = useState("BTC");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function trade() {
    setBusy(true); setErr(null);
    try { onTraded(await api.demoTrade({ base, side, quantity: qty })); setQty(""); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="demo-panel">
      <div className="demo-holdings">
        {demo.holdings.map((h) => (
          <div className="demo-h" key={h.symbol}>
            <span className="mono">{Number(h.quantity).toLocaleString(undefined, { maximumFractionDigits: 6 })} {h.symbol}</span>
            <span className="dim">${Number(h.usd_value).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
          </div>
        ))}
      </div>
      <div className="demo-form">
        <select value={base} onChange={(e) => setBase(e.target.value)}>{DEMO_COINS.map((c) => <option key={c}>{c}</option>)}</select>
        <div className="demo-seg">
          <button className={side === "BUY" ? "buy on" : ""} onClick={() => setSide("BUY")}>Buy</button>
          <button className={side === "SELL" ? "sell on" : ""} onClick={() => setSide("SELL")}>Sell</button>
        </div>
        <input value={qty} onChange={(e) => setQty(e.target.value)} inputMode="decimal" placeholder={`Qty ${base}`} />
        <button className="acc-btn primary" disabled={busy || !qty} onClick={trade}>{busy ? "…" : "Market " + side.toLowerCase()}</button>
      </div>
      {err && <p className="accs-err">{err}</p>}
    </div>
  );
}
