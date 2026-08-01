import { useEffect, useState } from "react";
import { api, ApiError, type AccountReports, type ApiKeyCreated, type ApiKeyRow, type StatementRow } from "../lib/api";
import { useLocale } from "../lib/locale";
import { navigate } from "../router";
import "./accountsections.css";

/* ============================================================ API Management */

export function ApiManagement() {
  const [keys, setKeys] = useState<ApiKeyRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null);

  const load = () => api.apiKeys().then(setKeys).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  useEffect(() => { load(); }, []);

  async function revoke(id: number) {
    setErr(null);
    try { await api.apiKeyRevoke(id); load(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }

  return (
    <div className="asec">
      <div className="asec-head"><h1>API Management</h1><button className="asec-add" onClick={() => setCreating(true)}>+ Create API key</button></div>
      <p className="asec-sub">Create keys to trade programmatically. The secret is shown once — store it safely.</p>
      {err && <p className="asec-err">{err}</p>}

      {creating && <CreateKeyModal onClose={() => setCreating(false)} onDone={(k) => { setCreating(false); setJustCreated(k); load(); }} />}
      {justCreated && <SecretModal created={justCreated} onClose={() => setJustCreated(null)} />}

      {keys && keys.length === 0 && <p className="asec-empty">No API keys yet.</p>}
      <div className="asec-keys">
        {keys?.map((k) => (
          <div className="asec-key" key={k.id}>
            <div className="asec-key-top">
              <b>{k.label}</b>
              <button className="asec-revoke" onClick={() => revoke(k.id)}>Revoke</button>
            </div>
            <div className="asec-key-id mono">{k.key}</div>
            <div className="asec-perms">
              <span className="asec-perm on">Read</span>
              <span className={`asec-perm ${k.can_trade ? "on" : ""}`}>Trade</span>
              <span className={`asec-perm ${k.can_withdraw ? "on danger" : ""}`}>Withdraw</span>
              <span className="asec-created">Created {new Date(k.created_at).toLocaleDateString()}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CreateKeyModal({ onClose, onDone }: { onClose: () => void; onDone: (k: ApiKeyCreated) => void }) {
  const [label, setLabel] = useState("");
  const [trade, setTrade] = useState(false);
  const [withdraw, setWithdraw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function create() {
    setBusy(true); setErr(null);
    try { onDone(await api.apiKeyCreate({ label: label.trim(), can_trade: trade, can_withdraw: withdraw })); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="asec-modal" onClick={onClose}>
      <div className="asec-box" onClick={(e) => e.stopPropagation()}>
        <div className="asec-box-h"><h3>Create API key</h3><button onClick={onClose}>✕</button></div>
        <label className="asec-field">Label<input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Trading bot" maxLength={60} /></label>
        <div className="asec-checks">
          <label><input type="checkbox" checked readOnly /> Read (always on)</label>
          <label><input type="checkbox" checked={trade} onChange={(e) => setTrade(e.target.checked)} /> Enable trading</label>
          <label><input type="checkbox" checked={withdraw} onChange={(e) => setWithdraw(e.target.checked)} /> Enable withdrawals (high risk)</label>
        </div>
        {err && <p className="asec-err">{err}</p>}
        <button className="asec-primary" disabled={busy || label.trim().length < 2} onClick={create}>{busy ? "…" : "Create key"}</button>
      </div>
    </div>
  );
}

function SecretModal({ created, onClose }: { created: ApiKeyCreated; onClose: () => void }) {
  return (
    <div className="asec-modal" onClick={onClose}>
      <div className="asec-box" onClick={(e) => e.stopPropagation()}>
        <div className="asec-box-h"><h3>Your API key</h3><button onClick={onClose}>✕</button></div>
        <p className="asec-warn">⚠ Copy the secret now — it won't be shown again.</p>
        <div className="asec-field">API Key<div className="asec-copy"><span className="mono">{created.key}</span><button onClick={() => navigator.clipboard?.writeText(created.key)}>Copy</button></div></div>
        <div className="asec-field">Secret<div className="asec-copy"><span className="mono">{created.secret}</span><button onClick={() => navigator.clipboard?.writeText(created.secret)}>Copy</button></div></div>
        <button className="asec-primary" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}

/* ============================================================ Account Statement */

export function Statement() {
  const [rows, setRows] = useState<StatementRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.accountStatement().then(setRows).catch((e) => setErr(e instanceof ApiError ? e.message : String(e))); }, []);

  return (
    <div className="asec">
      <h1>Account Statement</h1>
      <p className="asec-sub">Every movement on your accounts — deposits, trades, fees, transfers, rewards.</p>
      {err && <p className="asec-err">{err}</p>}
      {rows && rows.length === 0 && <p className="asec-empty">No transactions yet.</p>}
      {rows && rows.length > 0 && (
        <div className="asec-table">
          <div className="asec-h"><span>Time</span><span>Type</span><span>Asset</span><span className="num">Amount</span></div>
          {rows.map((r, i) => (
            <div className="asec-r" key={i}>
              <span className="dim">{new Date(r.time).toLocaleString()}</span>
              <span>{r.kind.replace(/_/g, " ").toLowerCase()}</span>
              <span className="mono">{r.asset}</span>
              <span className={`num mono ${Number(r.amount) >= 0 ? "up" : "down"}`}>{Number(r.amount) >= 0 ? "+" : ""}{Number(r.amount).toLocaleString(undefined, { maximumFractionDigits: 8 })}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ============================================================ Financial Reports */

export function Reports() {
  const [data, setData] = useState<AccountReports | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { fmt } = useLocale();
  useEffect(() => { api.accountReports().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : String(e))); }, []);

  return (
    <div className="asec">
      <h1>Financial Reports</h1>
      <p className="asec-sub">A summary of your account activity to date.</p>
      {err && <p className="asec-err">{err}</p>}
      {data && (
        <div className="asec-cards">
          <ReportCard label="Total deposits" value={fmt(Number(data.deposits_usd))} />
          <ReportCard label="Total withdrawals" value={fmt(Number(data.withdrawals_usd))} />
          <ReportCard label="Net inflow" value={fmt(Number(data.net_flow_usd))} />
          <ReportCard label="Trades" value={String(data.trades)} />
          <ReportCard label="Rewards earned" value={fmt(Number(data.rewards_usd))} />
          <ReportCard label="Referral earned" value={fmt(Number(data.referral_usd))} />
        </div>
      )}
    </div>
  );
}

function ReportCard({ label, value }: { label: string; value: string }) {
  return <div className="asec-report"><span>{label}</span><b>{value}</b></div>;
}

/* ============================================================ Payment */

export function Payment() {
  return (
    <div className="asec">
      <h1>Payment</h1>
      <p className="asec-sub">Fund your account and manage how you buy crypto.</p>
      <div className="asec-cards">
        <PayCard title="Buy with fiat" body="Buy crypto instantly with your local currency." cta="Buy Crypto" to="/dashboard/assets" tab="buy" />
        <PayCard title="P2P trading" body="Buy & sell with bank transfer, UPI and more, peer-to-peer." cta="Open P2P" to="/dashboard/p2p" />
        <PayCard title="Crypto deposit" body="Deposit crypto from an external wallet." cta="Deposit" to="/dashboard/assets" tab="deposit" />
        <PayCard title="Withdraw" body="Withdraw crypto to an external address." cta="Withdraw" to="/dashboard/assets" tab="withdraw" />
      </div>
    </div>
  );
}

function PayCard({ title, body, cta, to, tab }: { title: string; body: string; cta: string; to: string; tab?: string }) {
  return (
    <div className="asec-report pay">
      <b>{title}</b>
      <p>{body}</p>
      <button className="asec-primary" onClick={() => { if (tab) sessionStorage.setItem("assets_tab", tab); navigate(to); }}>{cta}</button>
    </div>
  );
}
