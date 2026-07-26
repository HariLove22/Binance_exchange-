import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  trimAmount,
  type Balance,
  type ConvertQuote,
  type DepositRecord,
  type OnrampQuote,
  type WalletNetwork,
  type WithdrawalRecord,
} from "../lib/api";

/**
 * The Spot wallet — balances, plus the deposit and withdrawal flows.
 *
 * There is no real custody, so the chain side is mocked: a deposit address is a plausible-looking
 * but non-functional string, and "Simulate deposit" stands in for the on-chain event a real
 * provider would deliver. Everything the exchange owns — the ledger postings, confirmations,
 * reserve-on-request, refund-on-fail — is real.
 */
export function Assets() {
  const [tab, setTab] = useState<"balances" | "buy" | "convert" | "deposit" | "withdraw">("balances");

  const tabs: [typeof tab, string][] = [
    ["balances", "Balances"],
    ["buy", "Buy Crypto"],
    ["convert", "Convert"],
    ["deposit", "Deposit"],
    ["withdraw", "Withdraw"],
  ];

  return (
    <div className="assets">
      <div className="assets-tabs">
        {tabs.map(([t, label]) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label}</button>
        ))}
      </div>

      {tab === "balances" && <Balances />}
      {tab === "buy" && <BuyCrypto />}
      {tab === "convert" && <Convert />}
      {tab === "deposit" && <Deposit />}
      {tab === "withdraw" && <Withdraw />}
    </div>
  );
}

/* ------------------------------------------------------------------ convert */

const CONVERT_ASSETS = ["USDT", "USDC", "BTC", "ETH", "SOL", "BNB", "AVAX", "POL", "TRX"];

function Convert() {
  const [balances, setBalances] = useState<Balance[]>([]);
  const [from, setFrom] = useState("USDT");
  const [to, setTo] = useState("BTC");
  const [amount, setAmount] = useState("100");
  const [quote, setQuote] = useState<ConvertQuote | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadBalances = useCallback(() => {
    api.balances().then(setBalances).catch(() => setBalances([]));
  }, []);
  useEffect(() => void loadBalances(), [loadBalances]);

  // Live quote as inputs change.
  useEffect(() => {
    if (!amount || Number(amount) <= 0 || from === to) { setQuote(null); return; }
    let cancelled = false;
    const id = setTimeout(() => {
      api.convertQuote({ from_asset: from, to_asset: to, from_amount: amount })
        .then((q) => !cancelled && setQuote(q))
        .catch(() => !cancelled && setQuote(null));
    }, 250);
    return () => { cancelled = true; clearTimeout(id); };
  }, [from, to, amount]);

  const avail = Number(balances.find((b) => b.asset === from)?.available ?? "0");

  async function doConvert() {
    setBusy(true);
    setNote(null);
    try {
      const q = await api.convertExecute({ from_asset: from, to_asset: to, from_amount: amount });
      setNote(`converted ${trimAmount(q.from_amount)} ${q.from_asset} → ${trimAmount(q.to_amount)} ${q.to_asset}`);
      loadBalances();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function flip() { setFrom(to); setTo(from); }

  return (
    <>
      <h2>Convert</h2>
      <p className="assets-muted">
        Instantly swap one asset for another at the live price — no order book, no slippage. The
        rate is locked in the quote; a 0.1% spread is the convert fee.
      </p>

      <div className="buy-card">
        <label className="buy-field">
          <span>From</span>
          <div className="buy-input">
            <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
            <select value={from} onChange={(e) => setFrom(e.target.value)}>
              {CONVERT_ASSETS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <span className="cv-avail">Available: {avail.toFixed(4)} {from}</span>
        </label>

        <button className="cv-flip" onClick={flip} title="Flip">⇅</button>

        <label className="buy-field">
          <span>To (est.)</span>
          <div className="buy-input">
            <input value={quote ? trimAmount(quote.to_amount) : "…"} readOnly />
            <select value={to} onChange={(e) => setTo(e.target.value)}>
              {CONVERT_ASSETS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </label>

        {quote && <p className="buy-rate">1 {from} ≈ {trimAmount(quote.rate)} {to}</p>}

        <button className="btn-gold buy-submit" onClick={doConvert} disabled={busy || !quote || from === to || avail < Number(amount)}>
          {busy ? "…" : from === to ? "Pick different assets" : avail < Number(amount) ? `Insufficient ${from}` : "Convert"}
        </button>
        {note && <p className="assets-note mono">{note}</p>}
      </div>
    </>
  );
}

/* --------------------------------------------------------------- buy crypto */

const CRYPTOS = ["BTC", "ETH", "SOL", "BNB", "USDT", "USDC", "AVAX", "POL", "TRX"];

function BuyCrypto() {
  const [currencies, setCurrencies] = useState<{ code: string; name: string }[]>([]);
  const [fiat, setFiat] = useState("INR");
  const [amount, setAmount] = useState("10000");
  const [asset, setAsset] = useState("BTC");
  const [quote, setQuote] = useState<OnrampQuote | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.onrampCurrencies().then((c) => setCurrencies(c)).catch(() => setCurrencies([]));
  }, []);

  // Live-ish quote as inputs change.
  useEffect(() => {
    if (!amount || Number(amount) <= 0) { setQuote(null); return; }
    let cancelled = false;
    const id = setTimeout(() => {
      api.onrampQuote({ fiat, fiat_amount: amount, asset })
        .then((q) => !cancelled && setQuote(q))
        .catch(() => !cancelled && setQuote(null));
    }, 250);
    return () => { cancelled = true; clearTimeout(id); };
  }, [fiat, amount, asset]);

  async function buy() {
    setBusy(true);
    setNote(null);
    try {
      const q = await api.onrampBuy({ fiat, fiat_amount: amount, asset });
      setNote(`bought ${trimAmount(q.crypto_amount)} ${q.asset} for ${q.fiat_amount} ${q.fiat}`);
      window.dispatchEvent(new CustomEvent("orders-changed"));
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2>Buy Crypto</h2>
      <p className="assets-muted">
        Pay in any currency; it converts to crypto at the live price. A mock on-ramp — a real one
        (MoonPay, Transak, a bank) would charge your card or take a transfer first. Credited through
        the deposit flow, so it stays backed and reconciled.
      </p>

      <div className="buy-card">
        <label className="buy-field">
          <span>You pay</span>
          <div className="buy-input">
            <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
            <select value={fiat} onChange={(e) => setFiat(e.target.value)}>
              {currencies.map((c) => <option key={c.code} value={c.code}>{c.code}</option>)}
            </select>
          </div>
        </label>

        <div className="buy-arrow">↓</div>

        <label className="buy-field">
          <span>You receive (est.)</span>
          <div className="buy-input">
            <input value={quote ? trimAmount(quote.crypto_amount) : "…"} readOnly />
            <select value={asset} onChange={(e) => setAsset(e.target.value)}>
              {CRYPTOS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </label>

        {quote && (
          <p className="buy-rate">
            1 {asset} ≈ ${Number(quote.unit_price_usd).toLocaleString()} · {amount} {fiat} ≈ ${quote.usd_amount}
          </p>
        )}

        <button className="btn-gold buy-submit" onClick={buy} disabled={busy || !quote}>
          {busy ? "…" : `Buy ${asset}`}
        </button>
        {note && <p className="assets-note mono">{note}</p>}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ balances */

function Balances() {
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
  useEffect(() => void load(), [load]);

  const has = balances && balances.length > 0;

  return (
    <>
      <div className="assets-head">
        <h2>Spot</h2>
        <button className="btn-outline-d" onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {error && <p className="assets-error">{error}</p>}
      {balances === null && !error && <p className="assets-muted">Loading…</p>}
      {balances !== null && !has && (
        <div className="assets-empty">
          <p>No assets yet.</p>
          <p className="assets-muted">Use the Deposit tab to add funds (mock custody, dev only).</p>
        </div>
      )}
      {has && (
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
              <span className="num at-locked">{trimAmount(b.locked)}</span>
            </div>
          ))}
        </div>
      )}
      <p className="assets-note">
        <strong>Available</strong> is spendable; <strong>In order</strong> is reserved against open
        orders — still yours, not spendable twice.
      </p>
    </>
  );
}

/* ------------------------------------------------------------------- deposit */

function useNetworks() {
  const [networks, setNetworks] = useState<WalletNetwork[]>([]);
  useEffect(() => {
    api.networks().then(setNetworks).catch(() => setNetworks([]));
  }, []);
  return networks;
}

function Deposit() {
  const networks = useNetworks();
  const [netId, setNetId] = useState<number | "">("");
  const [address, setAddress] = useState<{ address: string; memo: string | null } | null>(null);
  const [amount, setAmount] = useState("1000");
  const [deposits, setDeposits] = useState<DepositRecord[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadDeposits = useCallback(async () => {
    setDeposits(await api.deposits().catch(() => []));
  }, []);
  useEffect(() => void loadDeposits(), [loadDeposits]);

  async function getAddress() {
    if (!netId) return;
    setBusy(true);
    setNote(null);
    try {
      setAddress(await api.depositAddress(Number(netId)));
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function simulate() {
    if (!netId) return;
    setBusy(true);
    setNote(null);
    try {
      const d = await api.simulateDeposit(Number(netId), amount);
      setNote(`deposit #${d.id} ${d.status} — ${d.amount} ${d.asset}`);
      await loadDeposits();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const enabled = networks.filter((n) => n.deposit_enabled);

  return (
    <>
      <h2>Deposit</h2>
      {enabled.length === 0 && (
        <p className="assets-muted">
          No networks are enabled for deposit. In dev, an admin can enable them; the seeder ships
          them off so nothing accepts real funds before custody exists.
        </p>
      )}
      <div className="wallet-form">
        <label>
          <span>Network</span>
          <select value={netId} onChange={(e) => setNetId(Number(e.target.value) || "")}>
            <option value="">select…</option>
            {enabled.map((n) => (
              <option key={n.asset_network_id} value={n.asset_network_id}>
                {n.asset} · {n.chain_name}
              </option>
            ))}
          </select>
        </label>
        <button className="btn-outline-d" onClick={getAddress} disabled={busy || !netId}>
          Get address
        </button>
      </div>

      {address && (
        <div className="deposit-address">
          <span className="da-label">Deposit address (mock — do not send real funds)</span>
          <code>{address.address}</code>
          {address.memo && <span className="da-memo">Memo: {address.memo}</span>}
        </div>
      )}

      <div className="wallet-form" style={{ marginTop: "1rem" }}>
        <label>
          <span>Simulate a deposit</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
        </label>
        <button className="btn-gold" onClick={simulate} disabled={busy || !netId}>
          Simulate deposit
        </button>
      </div>
      {note && <p className="assets-note mono">{note}</p>}

      {deposits.length > 0 && (
        <div className="assets-table" style={{ marginTop: "1.25rem" }}>
          <div className="at-head" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
            <span>Asset</span>
            <span>Chain</span>
            <span className="num">Amount</span>
            <span>Status</span>
          </div>
          {deposits.map((d) => (
            <div className="at-row" key={d.id} style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
              <span className="mono">{d.asset}</span>
              <span className="mono">{d.chain}</span>
              <span className="num">{trimAmount(d.amount)}</span>
              <span className="mono">{d.status}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ withdraw */

function Withdraw() {
  const networks = useNetworks();
  const [netId, setNetId] = useState<number | "">("");
  const [address, setAddress] = useState("");
  const [amount, setAmount] = useState("");
  const [withdrawals, setWithdrawals] = useState<WithdrawalRecord[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setWithdrawals(await api.withdrawals().catch(() => []));
  }, []);
  useEffect(() => void load(), [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!netId) return;
    setBusy(true);
    setNote(null);
    try {
      const w = await api.withdraw({ asset_network_id: Number(netId), to_address: address, amount });
      setNote(`withdrawal #${w.id} ${w.status} — reserved ${trimAmount(w.amount)} + ${trimAmount(w.fee)} fee`);
      await load();
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(id: number) {
    setBusy(true);
    try {
      await api.confirmWithdrawal(id);
      await load();
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const enabled = networks.filter((n) => n.withdraw_enabled);
  const selected = networks.find((n) => n.asset_network_id === netId);

  return (
    <>
      <h2>Withdraw</h2>
      <form className="wallet-form-col" onSubmit={submit}>
        <label>
          <span>Network</span>
          <select value={netId} onChange={(e) => setNetId(Number(e.target.value) || "")} required>
            <option value="">select…</option>
            {enabled.map((n) => (
              <option key={n.asset_network_id} value={n.asset_network_id}>
                {n.asset} · {n.chain_name} (fee {trimAmount(n.withdrawal_fee)})
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Destination address</span>
          <input value={address} onChange={(e) => setAddress(e.target.value)} required minLength={4} />
        </label>
        <label>
          <span>Amount{selected ? ` (fee ${trimAmount(selected.withdrawal_fee)} ${selected.asset})` : ""}</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" required />
        </label>
        <button className="btn-gold" disabled={busy || !netId}>
          Request withdrawal
        </button>
      </form>
      {note && <p className="assets-note mono">{note}</p>}

      <p className="assets-muted" style={{ marginTop: "0.75rem" }}>
        Real withdrawals also gate on 2FA, email confirmation and an address whitelist with a
        time-lock. Those are not built yet — the funds move AVAILABLE → PENDING on request and only
        leave on confirmation. "Confirm" below stands in for the chain-confirmation event.
      </p>

      {withdrawals.length > 0 && (
        <div className="assets-table" style={{ marginTop: "1rem" }}>
          <div className="at-head" style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
            <span>Asset</span>
            <span className="num">Amount</span>
            <span>Status</span>
            <span></span>
          </div>
          {withdrawals.map((w) => (
            <div className="at-row" key={w.id} style={{ gridTemplateColumns: "1fr 1fr 1fr 1fr" }}>
              <span className="mono">{w.asset}</span>
              <span className="num">{trimAmount(w.amount)}</span>
              <span className="mono">{w.status}</span>
              <span className="num">
                {w.status === "BROADCAST" && (
                  <button className="btn-outline-d small" onClick={() => confirm(w.id)} disabled={busy}>
                    Confirm
                  </button>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
