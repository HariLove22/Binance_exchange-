import { useCallback, useEffect, useState } from "react";
import { api, ApiError, trimAmount, type Balance } from "../lib/api";

/**
 * The Spot wallet — real balances from the ledger, the page the Binance "Assets → Spot"
 * screenshot maps to.
 *
 * `available` and `locked` are shown side by side, always. Once orders exist, placing one moves
 * funds from available to locked, and a UI that showed only available would read as "my money
 * disappeared". The money is still the user's — locked is reserved, not gone.
 *
 * Amounts are formatted from the server's fixed-scale strings and never parsed into a number. The
 * ledger keeps 18 decimals of precision; a `Number()` here would quietly throw some of it away.
 */
export function Assets() {
  const [balances, setBalances] = useState<Balance[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setBalances(await api.balances());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hasFunds = balances && balances.length > 0;

  return (
    <div className="assets">
      <div className="assets-head">
        <h2>Spot</h2>
        <button className="btn-outline-d" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      {error && <p className="assets-error">{error}</p>}

      {balances === null && !error && <p className="assets-muted">Loading…</p>}

      {balances !== null && !hasFunds && (
        <div className="assets-empty">
          <p>No assets yet.</p>
          <p className="assets-muted">
            There is no deposit pipeline — that needs a custody provider, and there isn't one yet.
            For development, credit test funds from the server:
          </p>
          <pre>python -m app.dev_credit YOUR_EMAIL USDT 5000</pre>
          <p className="assets-muted">
            That posts a real double-entry ledger transaction, not a hardcoded number.
          </p>
        </div>
      )}

      {hasFunds && (
        <div className="assets-table">
          <div className="at-head">
            <span>Asset</span>
            <span className="num">Total</span>
            <span className="num">Available</span>
            <span className="num">In order</span>
          </div>
          {balances!.map((b) => (
            <div className="at-row" key={b.asset}>
              <span className="at-asset">
                <span className="at-badge">{b.asset.slice(0, 3)}</span>
                {b.asset}
              </span>
              <span className="num">{trimAmount(b.total)}</span>
              <span className="num">{trimAmount(b.available)}</span>
              <span className="num at-locked" title="Reserved against open orders">
                {trimAmount(b.locked)}
              </span>
            </div>
          ))}
        </div>
      )}

      <p className="assets-note">
        <strong>Available</strong> is spendable. <strong>In order</strong> (locked) is reserved
        against an open order — still yours, not spendable twice. Funds are locked <em>before</em>
        an order reaches the matching engine, never after: the engine has no database and cannot
        check balances, so an unfunded order reaching it would produce a trade the ledger cannot
        settle.
      </p>
    </div>
  );
}
