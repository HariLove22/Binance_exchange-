import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { isNonZero, useBalances } from "./useBalances";

const COIN_STYLE: Record<string, { bg: string; fg: string; glyph: string }> = {
  BTC: { bg: "#F7931A22", fg: "#F7931A", glyph: "₿" },
  ETH: { bg: "#627EEA22", fg: "#627EEA", glyph: "Ξ" },
  USDT: { bg: "#26A17B22", fg: "#26A17B", glyph: "₮" },
  INR: { bg: "#F0B90B22", fg: "#F0B90B", glyph: "₹" },
};

export function Assets() {
  const { balances, loading, error, reload } = useBalances();
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("10000");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [hideZero, setHideZero] = useState(false);

  async function addFunds(e: FormEvent) {
    e.preventDefault();
    setMsg("");
    setErr("");
    setBusy(true);
    try {
      const res = await api.faucet(asset, amount);
      setMsg(`Credited ${res.credited} ${res.asset}`);
      await reload();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Could not add funds");
    } finally {
      setBusy(false);
    }
  }

  const shown = hideZero ? balances.filter((b) => isNonZero(b.total)) : balances;

  return (
    <div>
      <div className="page-head">
        <h1>Assets</h1>
        <label className="checkbox-inline">
          <input type="checkbox" checked={hideZero} onChange={(e) => setHideZero(e.target.checked)} />
          Hide zero balances
        </label>
      </div>

      {/* Dev faucet — stands in for a deposit while Phase 1 is paper trading. */}
      <form className="faucet" onSubmit={addFunds}>
        <div className="faucet-title">Add test funds <span className="tag">DEV</span></div>
        <div className="faucet-row">
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {balances.map((b) => (
              <option key={b.asset} value={b.asset}>{b.asset}</option>
            ))}
          </select>
          <input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="Amount"
            inputMode="decimal"
          />
          <button className="btn-gold" type="submit" disabled={busy}>
            {busy ? "Adding…" : "Add funds"}
          </button>
        </div>
        {msg && <div className="faucet-msg ok">{msg}</div>}
        {err && <div className="faucet-msg err">{err}</div>}
      </form>

      {error && <div className="faucet-msg err" style={{ marginBottom: "1rem" }}>{error}</div>}

      <div className="table-card">
        <table className="asset-table">
          <thead>
            <tr>
              <th>Asset</th>
              <th className="num">Available</th>
              <th className="num">In orders</th>
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} className="empty">Loading…</td></tr>
            ) : shown.length === 0 ? (
              <tr><td colSpan={4} className="empty">No balances yet — add test funds above.</td></tr>
            ) : (
              shown.map((b) => {
                const s = COIN_STYLE[b.asset] ?? { bg: "#ffffff11", fg: "#eaecef", glyph: "◈" };
                return (
                  <tr key={b.asset}>
                    <td>
                      <span className="coin">
                        <span className="coin-badge" style={{ background: s.bg, color: s.fg }}>{s.glyph}</span>
                        <span>
                          <strong>{b.asset}</strong>
                          <em>{b.name}</em>
                        </span>
                      </span>
                    </td>
                    <td className="num mono">{b.available}</td>
                    <td className="num mono dim">{b.locked}</td>
                    <td className="num mono strong">{b.total}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
