import { useCallback, useEffect, useState } from "react";
import { api, ApiError, trimAmount, type LpToken, type LpOffering, type LpPool } from "../lib/api";
import { useKycApproved, KycRequiredNotice } from "./KycGate";
import "./launchpad.css";

type Tab = "create" | "offerings" | "trade";

/**
 * Token Launchpad — create a coin (synthetic ledger asset), run an ICO/STO offering, pool it against
 * USDT (AMM), then swap. Everything settles on the double-entry ledger; the "coin value & price" panel
 * shows the live price and fully-diluted valuation.
 */
export function Launchpad() {
  const [tab, setTab] = useState<Tab>("create");
  const kycOk = useKycApproved();

  return (
    <div className="lp">
      <div className="lp-head">
        <h1>Launchpad</h1>
        <p className="lp-sub">Create a coin, raise funds with an ICO/STO, pool it, and trade — all on the exchange ledger.</p>
      </div>
      <div className="lp-tabs">
        <button className={tab === "create" ? "on" : ""} onClick={() => setTab("create")}>Create & Manage</button>
        <button className={tab === "offerings" ? "on" : ""} onClick={() => setTab("offerings")}>Offerings (ICO/STO)</button>
        <button className={tab === "trade" ? "on" : ""} onClick={() => setTab("trade")}>Pools & Swap</button>
      </div>
      {kycOk === false ? <div className="lp-card"><KycRequiredNotice /></div> : (
        <>
          {tab === "create" && <CreateTab />}
          {tab === "offerings" && <OfferingsTab />}
          {tab === "trade" && <TradeTab />}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ create + manage */

function CreateTab() {
  const [tokens, setTokens] = useState<LpToken[]>([]);
  const load = useCallback(() => api.lpMyTokens().then(setTokens).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="lp-grid">
      <CreateForm onDone={load} />
      <div className="lp-card">
        <h2>My coins</h2>
        {tokens.length === 0 && <p className="lp-empty">No coins yet. Create one on the left.</p>}
        {tokens.map((t) => <TokenRow key={t.id} token={t} onChange={load} />)}
      </div>
    </div>
  );
}

function CreateForm({ onDone }: { onDone: () => void }) {
  const [symbol, setSymbol] = useState("");
  const [name, setName] = useState("");
  const [supply, setSupply] = useState("1000000");
  const [purpose, setPurpose] = useState("");
  const [audience, setAudience] = useState("");
  const [type, setType] = useState<"ICO" | "STO">("ICO");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function submit() {
    setBusy(true); setNote(null);
    try {
      await api.lpCreateToken({ symbol, name, total_supply: supply, purpose, target_audience: audience, offering_type: type });
      setNote(`✓ ${symbol.toUpperCase()} created — ${trimAmount(supply)} minted to you`);
      setSymbol(""); setName(""); onDone();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="lp-card">
      <h2>Create a coin</h2>
      <label className="lp-field">Symbol<input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="MOON" maxLength={12} /></label>
      <label className="lp-field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Moon Coin" /></label>
      <label className="lp-field">Total supply<input value={supply} onChange={(e) => setSupply(e.target.value)} inputMode="decimal" /></label>
      <label className="lp-field">Purpose<input value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="What is this coin for?" /></label>
      <label className="lp-field">Target audience<input value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="Who is it for?" /></label>
      <label className="lp-field">Offering type
        <div className="lp-seg">
          <button className={type === "ICO" ? "on" : ""} onClick={() => setType("ICO")}>ICO (utility)</button>
          <button className={type === "STO" ? "on" : ""} onClick={() => setType("STO")}>STO (security)</button>
        </div>
      </label>
      <button className="lp-btn primary" disabled={busy || !symbol || !name} onClick={submit}>{busy ? "…" : "Create coin"}</button>
      {note && <p className="lp-note">{note}</p>}
    </div>
  );
}

function TokenRow({ token, onChange }: { token: LpToken; onChange: () => void }) {
  const [open, setOpen] = useState<"offer" | "pool" | null>(null);
  return (
    <div className="lp-token">
      <div className="lp-token-top">
        <b>{token.symbol}</b> <span className="lp-dim">{token.name}</span>
        <span className={`lp-badge ${token.offering_type.toLowerCase()}`}>{token.offering_type}</span>
        <span className="lp-token-bal">{trimAmount(token.balance)}</span>
      </div>
      <div className="lp-token-actions">
        <button onClick={() => setOpen(open === "offer" ? null : "offer")}>Open offering</button>
        <button onClick={() => setOpen(open === "pool" ? null : "pool")}>Create pool</button>
      </div>
      {open === "offer" && <OfferingForm token={token} onDone={() => { setOpen(null); onChange(); }} />}
      {open === "pool" && <PoolForm token={token} onDone={() => { setOpen(null); onChange(); }} />}
    </div>
  );
}

function OfferingForm({ token, onDone }: { token: LpToken; onDone: () => void }) {
  const [price, setPrice] = useState("0.5");
  const [forSale, setForSale] = useState("100000");
  const [softCap, setSoftCap] = useState("0");
  const [days, setDays] = useState("7");
  const [lockup, setLockup] = useState("0");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const p = Number(price) || 0, fs = Number(forSale) || 0, supply = Number(token.total_supply) || 0;
  const raise = p * fs, fdv = p * supply;

  async function submit() {
    setBusy(true); setNote(null);
    try {
      await api.lpOpenOffering({
        token_symbol: token.symbol, sale_price: price, tokens_for_sale: forSale, soft_cap: softCap,
        duration_hours: Math.max(1, Number(days) * 24), requires_whitelist: token.offering_type === "STO",
        lockup_days: token.offering_type === "STO" ? Number(lockup) : 0,
      });
      setNote("✓ Offering opened"); onDone();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="lp-inline">
      <div className="lp-inline-row">
        <label>Sale price (USDT)<input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" /></label>
        <label>Tokens for sale<input value={forSale} onChange={(e) => setForSale(e.target.value)} inputMode="decimal" /></label>
      </div>
      <div className="lp-inline-row">
        <label>Soft cap (USDT)<input value={softCap} onChange={(e) => setSoftCap(e.target.value)} inputMode="decimal" /></label>
        <label>Duration (days)<input value={days} onChange={(e) => setDays(e.target.value)} inputMode="decimal" /></label>
        {token.offering_type === "STO" && <label>Lockup (days)<input value={lockup} onChange={(e) => setLockup(e.target.value)} inputMode="decimal" /></label>}
      </div>
      <Valuation price={p} raise={raise} fdv={fdv} />
      {token.offering_type === "STO" && <p className="lp-note">STO: only whitelisted investors can buy; tokens lock for the lockup period.</p>}
      <button className="lp-btn primary" disabled={busy} onClick={submit}>{busy ? "…" : "Open offering"}</button>
      {note && <p className="lp-note">{note}</p>}
    </div>
  );
}

function PoolForm({ token, onDone }: { token: LpToken; onDone: () => void }) {
  const [tokenAmt, setTokenAmt] = useState("100000");
  const [quoteAmt, setQuoteAmt] = useState("50000");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const t = Number(tokenAmt) || 0, q = Number(quoteAmt) || 0, supply = Number(token.total_supply) || 0;
  const price = t > 0 ? q / t : 0, fdv = price * supply;

  async function submit() {
    setBusy(true); setNote(null);
    try {
      const r = await api.lpCreatePool({ token_symbol: token.symbol, token_amt: tokenAmt, quote_amt: quoteAmt });
      setNote(`✓ Pool live — price ${trimAmount(r.price)} USDT`); onDone();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="lp-inline">
      <div className="lp-inline-row">
        <label>{token.symbol} amount<input value={tokenAmt} onChange={(e) => setTokenAmt(e.target.value)} inputMode="decimal" /></label>
        <label>USDT amount<input value={quoteAmt} onChange={(e) => setQuoteAmt(e.target.value)} inputMode="decimal" /></label>
      </div>
      <Valuation price={price} fdv={fdv} />
      <button className="lp-btn primary" disabled={busy} onClick={submit}>{busy ? "…" : "Create pool & seed liquidity"}</button>
      {note && <p className="lp-note">{note}</p>}
    </div>
  );
}

/** Coin value & price panel — deterministic, from the numbers entered. */
function Valuation({ price, raise, fdv }: { price: number; raise?: number; fdv: number }) {
  return (
    <div className="lp-val">
      <div><span>Coin price</span><b>{price > 0 ? `$${price.toLocaleString(undefined, { maximumFractionDigits: 8 })}` : "—"}</b></div>
      {raise !== undefined && <div><span>Raise (sellout)</span><b>${raise.toLocaleString()}</b></div>}
      <div><span>Valuation (FDV)</span><b>{fdv > 0 ? `$${fdv.toLocaleString()}` : "—"}</b></div>
    </div>
  );
}

/* ------------------------------------------------------------------ offerings */

function OfferingsTab() {
  const [offs, setOffs] = useState<LpOffering[]>([]);
  const load = useCallback(() => api.lpOfferings().then(setOffs).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="lp-card">
      <h2>Live offerings</h2>
      {offs.length === 0 && <p className="lp-empty">No offerings yet.</p>}
      {offs.map((o) => <OfferingCard key={o.id} off={o} onChange={load} />)}
    </div>
  );
}

function OfferingCard({ off, onChange }: { off: LpOffering; onChange: () => void }) {
  const [amt, setAmt] = useState("");
  const [wl, setWl] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const pct = Number(off.hard_cap) > 0 ? (Number(off.raised) / Number(off.hard_cap)) * 100 : 0;

  async function run(fn: () => Promise<unknown>, ok: string) {
    setNote(null);
    try { await fn(); setNote(ok); onChange(); } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); }
  }

  return (
    <div className="lp-offer">
      <div className="lp-offer-top">
        <b>{off.symbol}</b> <span className={`lp-badge ${off.type.toLowerCase()}`}>{off.type}</span>
        <span className="lp-dim">@ {trimAmount(off.sale_price)} USDT</span>
        <span className={`lp-status s-${off.status.toLowerCase()}`}>{off.status}</span>
      </div>
      <div className="lp-bar"><div className="lp-bar-fill" style={{ width: `${Math.min(100, pct)}%` }} /></div>
      <div className="lp-offer-meta">Raised {trimAmount(off.raised)} / {trimAmount(off.hard_cap)} USDT · sold {trimAmount(off.tokens_sold)}{off.requires_whitelist ? " · whitelist" : ""}{off.lockup_until ? " · lockup" : ""}</div>
      {(off.status === "DRAFT" || off.status === "LIVE") && (
        <div className="lp-offer-actions">
          <input value={amt} onChange={(e) => setAmt(e.target.value)} inputMode="decimal" placeholder="USDT to buy" />
          <button className="lp-btn primary" disabled={!amt} onClick={() => run(() => api.lpBuyOffering(off.id, amt), "✓ Bought")}>Buy</button>
          <button className="lp-btn" onClick={() => run(() => api.lpCloseOffering(off.id), "✓ Closed")}>Close</button>
        </div>
      )}
      {off.requires_whitelist && (off.status === "DRAFT" || off.status === "LIVE") && (
        <div className="lp-offer-actions">
          <input value={wl} onChange={(e) => setWl(e.target.value)} placeholder="Investor email to whitelist" />
          <button className="lp-btn" disabled={!wl} onClick={() => run(() => api.lpWhitelist(off.id, wl), "✓ Whitelisted")}>Whitelist</button>
        </div>
      )}
      {note && <p className="lp-note">{note}</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ pools & swap */

function TradeTab() {
  const [pools, setPools] = useState<LpPool[]>([]);
  const load = useCallback(() => api.lpPools().then(setPools).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="lp-grid">
      <SwapWidget pools={pools} onDone={load} />
      <div className="lp-card">
        <h2>Pools</h2>
        {pools.length === 0 && <p className="lp-empty">No pools yet. Create one from a coin.</p>}
        {pools.map((p) => (
          <div className="lp-pool" key={p.id}>
            <div className="lp-pool-top"><b>{p.symbol}</b>/USDT <span className="lp-dim">{p.name}</span></div>
            <div className="lp-pool-meta">
              <span>Price <b>${p.price ? trimAmount(p.price) : "—"}</b></span>
              <span>FDV <b>{p.fdv_usd ? `$${Number(p.fdv_usd).toLocaleString()}` : "—"}</b></span>
              <span>TVL <b>{p.tvl_usd ? `$${Number(p.tvl_usd).toLocaleString()}` : "—"}</b></span>
              {Number(p.my_shares) > 0 && <span>My LP <b>{trimAmount(p.my_shares)}</b></span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SwapWidget({ pools, onDone }: { pools: LpPool[]; onDone: () => void }) {
  const [poolId, setPoolId] = useState<number | null>(null);
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [amt, setAmt] = useState("");
  const [quote, setQuote] = useState<{ amount_out: string; price_impact: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const pool = pools.find((p) => p.id === poolId) ?? pools[0];
  useEffect(() => { if (!poolId && pools.length) setPoolId(pools[0].id); }, [pools, poolId]);

  useEffect(() => {
    if (!pool || !amt || Number(amt) <= 0) { setQuote(null); return; }
    let live = true;
    api.lpSwapQuote(pool.id, side, amt).then((q) => live && setQuote(q)).catch(() => live && setQuote(null));
    return () => { live = false; };
  }, [pool, side, amt]);

  async function submit() {
    if (!pool) return;
    setBusy(true); setNote(null);
    try {
      const r = await api.lpSwap({ pool_id: pool.id, side, amount_in: amt });
      setNote(`✓ Got ${trimAmount(r.amount_out)} ${side === "BUY" ? pool.symbol : "USDT"}`);
      setAmt(""); setQuote(null); onDone();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }

  const inUnit = side === "BUY" ? "USDT" : pool?.symbol ?? "";
  const outUnit = side === "BUY" ? pool?.symbol ?? "" : "USDT";

  return (
    <div className="lp-card">
      <h2>Swap</h2>
      {!pool ? <p className="lp-empty">No pools to trade yet.</p> : (
        <>
          <label className="lp-field">Pool
            <select value={pool.id} onChange={(e) => setPoolId(Number(e.target.value))}>
              {pools.map((p) => <option key={p.id} value={p.id}>{p.symbol}/USDT · ${p.price ? trimAmount(p.price) : "—"}</option>)}
            </select>
          </label>
          <div className="lp-seg">
            <button className={side === "BUY" ? "on buy" : ""} onClick={() => setSide("BUY")}>Buy {pool.symbol}</button>
            <button className={side === "SELL" ? "on sell" : ""} onClick={() => setSide("SELL")}>Sell {pool.symbol}</button>
          </div>
          <label className="lp-field">Pay ({inUnit})<input value={amt} onChange={(e) => setAmt(e.target.value)} inputMode="decimal" placeholder="0" /></label>
          <div className="lp-swap-out">
            <span>You receive</span>
            <b>{quote ? `${trimAmount(quote.amount_out)} ${outUnit}` : "—"}</b>
          </div>
          {quote && <div className="lp-impact">Price impact {(Number(quote.price_impact) * 100).toFixed(2)}%</div>}
          <button className={`lp-btn primary ${side.toLowerCase()}`} disabled={busy || !quote} onClick={submit}>{busy ? "…" : `${side} ${pool.symbol}`}</button>
          {note && <p className="lp-note">{note}</p>}
        </>
      )}
    </div>
  );
}
