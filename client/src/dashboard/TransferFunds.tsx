import { useCallback, useEffect, useState } from "react";
import { api, ApiError, trimAmount, type Balance } from "../lib/api";
import "./transfer.css";

// User-facing wallets funds can move between (same user, own money).
const WALLETS = [
  { key: "SPOT", label: "Spot" },
  { key: "FUNDING", label: "Funding" },
  { key: "MARGIN", label: "Cross Margin" },
  { key: "FUTURES", label: "Futures" },
];

/** Universal internal transfer — move any asset between your own wallets (Spot ⇄ Margin ⇄ Futures). */
export function TransferModal({ onClose, onDone }: { onClose: () => void; onDone?: () => void }) {
  const [from, setFrom] = useState("SPOT");
  const [to, setTo] = useState("FUTURES");
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("");
  const [bals, setBals] = useState<Balance[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const loadBals = useCallback(() => api.balances(from).then(setBals).catch(() => setBals([])), [from]);
  useEffect(() => { loadBals(); }, [loadBals]);

  const avail = Number(bals.find((b) => b.asset === asset)?.available ?? 0);
  // Assets to choose from: whatever the source wallet holds, else common ones.
  const assetOptions = bals.length ? bals.map((b) => b.asset) : ["USDT", "BTC", "ETH", "BNB", "SOL"];

  function swap() { setFrom(to); setTo(from); }

  async function submit() {
    if (!amount || Number(amount) <= 0) { setNote("enter an amount"); return; }
    setBusy(true); setNote(null);
    try {
      await api.walletTransfer({ asset, amount, from_wallet: from, to_wallet: to });
      setNote(`✓ Sent ${trimAmount(amount)} ${asset} to ${WALLETS.find((w) => w.key === to)?.label}`);
      setAmount(""); loadBals(); onDone?.();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="xfer-modal" onClick={onClose}>
      <div className="xfer-box" onClick={(e) => e.stopPropagation()}>
        <div className="xfer-head"><h3>Transfer</h3><button className="xfer-x" onClick={onClose}>✕</button></div>

        <div className="xfer-route">
          <label className="xfer-field">From
            <select value={from} onChange={(e) => { const v = e.target.value; if (v === to) setTo(from); setFrom(v); }}>
              {WALLETS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
            </select>
          </label>
          <button className="xfer-swap" onClick={swap} title="Swap" aria-label="Swap direction">⇅</button>
          <label className="xfer-field">To
            <select value={to} onChange={(e) => { const v = e.target.value; if (v === from) setFrom(to); setTo(v); }}>
              {WALLETS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
            </select>
          </label>
        </div>

        <label className="xfer-field">Coin
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {[...new Set([asset, ...assetOptions])].map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>

        <label className="xfer-field">Amount
          <div className="xfer-amt">
            <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="0" />
            <button className="xfer-max" onClick={() => setAmount(String(avail))}>MAX</button>
          </div>
        </label>
        <div className="xfer-avail">Available in {WALLETS.find((w) => w.key === from)?.label}: <b>{trimAmount(String(avail))} {asset}</b></div>

        {note && <p className="xfer-note">{note}</p>}
        <button className="xfer-submit" disabled={busy || !amount} onClick={submit}>{busy ? "…" : "Confirm transfer"}</button>
      </div>
    </div>
  );
}
