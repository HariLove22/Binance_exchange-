import { useEffect, useState } from "react";
import { api, ApiError, type SubAccount } from "../lib/api";
import { useLocale } from "../lib/locale";
import "./subaccounts.css";

const ASSETS = ["USDT", "BTC", "ETH", "BNB"];

/**
 * Sub-accounts: extra accounts under the master, each with its own balances, for separating desks or
 * strategies. The master creates them and moves funds in and out; sub-accounts can't log in on their
 * own. Transfers are on-books and instant.
 */
export function SubAccounts() {
  const [subs, setSubs] = useState<SubAccount[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [xfer, setXfer] = useState<SubAccount | null>(null);
  const { fmt } = useLocale();

  const load = () => api.subAccounts().then(setSubs).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  useEffect(() => { load(); }, []);

  const total = subs?.reduce((s, a) => s + Number(a.value_usd), 0) ?? 0;

  return (
    <div className="sa">
      {creating && <CreateModal onClose={() => setCreating(false)} onDone={() => { setCreating(false); load(); }} />}
      {xfer && <TransferModal sub={xfer} onClose={() => setXfer(null)} onDone={(list) => { setSubs(list); setXfer(null); }} />}

      <div className="sa-head">
        <div>
          <h1>Sub Accounts</h1>
          <p className="sa-sub">Separate accounts for different strategies or desks. Move funds in and out anytime.</p>
        </div>
        <div className="sa-head-right">
          <button className="sa-add" onClick={() => setCreating(true)}>+ Create sub-account</button>
          <div className="sa-total"><span>Sub-accounts value</span><b>{fmt(total)}</b></div>
        </div>
      </div>

      {err && <p className="sa-err">{err}</p>}

      {subs && subs.length === 0 && (
        <div className="sa-empty">
          <p>No sub-accounts yet.</p>
          <p className="sa-sub">Create one to ring-fence funds for a bot, a team member, or a strategy.</p>
        </div>
      )}

      <div className="sa-list">
        {subs?.map((s) => (
          <div className="sa-card" key={s.id}>
            <div className="sa-card-top">
              <div className="sa-avatar">{s.label[0]?.toUpperCase()}</div>
              <div className="sa-id">
                <div className="sa-label">{s.label}</div>
                <div className="sa-meta">ID #{s.id} · created {new Date(s.created_at).toLocaleDateString()}</div>
              </div>
              <div className="sa-val">{fmt(Number(s.value_usd))}</div>
            </div>
            <div className="sa-bals">
              {s.balances.length === 0 ? <span className="dim">No funds — transfer some in.</span> :
                s.balances.map((b) => <span key={b.asset} className="sa-bal">{Number(b.available).toLocaleString(undefined, { maximumFractionDigits: 6 })} {b.asset}</span>)}
            </div>
            <button className="sa-xfer-btn" onClick={() => setXfer(s)}>Transfer funds</button>
          </div>
        ))}
      </div>
    </div>
  );
}

function CreateModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function create() {
    setBusy(true); setErr(null);
    try { await api.subCreate(label.trim()); onDone(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="sa-modal" onClick={onClose}>
      <div className="sa-box" onClick={(e) => e.stopPropagation()}>
        <div className="sa-box-h"><h3>Create sub-account</h3><button onClick={onClose}>✕</button></div>
        <label className="sa-field">Name<input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Grid Bot, Desk 2" maxLength={60} /></label>
        {err && <p className="sa-err">{err}</p>}
        <button className="sa-primary" disabled={busy || label.trim().length < 2} onClick={create}>{busy ? "…" : "Create"}</button>
      </div>
    </div>
  );
}

function TransferModal({ sub, onClose, onDone }: { sub: SubAccount; onClose: () => void; onDone: (list: SubAccount[]) => void }) {
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [toSub, setToSub] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function go() {
    setBusy(true); setErr(null);
    try { onDone(await api.subTransfer({ sub_id: sub.id, asset, amount, to_sub: toSub })); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }
  return (
    <div className="sa-modal" onClick={onClose}>
      <div className="sa-box" onClick={(e) => e.stopPropagation()}>
        <div className="sa-box-h"><h3>Transfer · {sub.label}</h3><button onClick={onClose}>✕</button></div>
        <div className="sa-seg">
          <button className={toSub ? "on" : ""} onClick={() => setToSub(true)}>Main → Sub</button>
          <button className={!toSub ? "on" : ""} onClick={() => setToSub(false)}>Sub → Main</button>
        </div>
        <div className="sa-frow">
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>{ASSETS.map((a) => <option key={a}>{a}</option>)}</select>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Amount" />
        </div>
        {err && <p className="sa-err">{err}</p>}
        <button className="sa-primary" disabled={busy || !amount} onClick={go}>{busy ? "…" : "Transfer"}</button>
      </div>
    </div>
  );
}
