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

  const load = useCallback(async () => {
    setErr(null);
    try { setOv(await api.accountOverview()); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const total = ov ? Number(ov.spot_usd) + (ov.margin.open ? Number(ov.margin.equity_usd) : 0) : 0;

  return (
    <div className="accs">
      <div className="accs-head">
        <div>
          <h1>Accounts</h1>
          <p className="accs-sub">Your trading accounts and their estimated value.</p>
        </div>
        <div className="accs-total">
          <span>Estimated total (real)</span>
          <b>${total.toLocaleString(undefined, { maximumFractionDigits: 2 })}</b>
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
