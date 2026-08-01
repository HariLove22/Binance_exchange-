import { useCallback, useEffect, useState } from "react";
import { api, ApiError, trimAmount, type OptionChain, type OptionPosition } from "../lib/api";
import { useKycApproved, KycRequiredNotice } from "./KycGate";
import "./options.css";

const COINS = ["BTC", "ETH", "BNB", "SOL"];

/**
 * Options: buy European calls/puts, cash-settled in USDT. Pick underlying, expiry, strike and type;
 * see the Black-Scholes premium; buy. Positions auto-settle at expiry against the mark price.
 */
export function Options() {
  const [underlying, setUnderlying] = useState("BTC");
  const [chain, setChain] = useState<OptionChain | null>(null);
  const [positions, setPositions] = useState<OptionPosition[]>([]);
  const kycOk = useKycApproved();

  const loadPositions = useCallback(() => api.optionsPositions().then(setPositions).catch(() => {}), []);
  useEffect(() => { api.optionsChain(underlying).then(setChain).catch(() => setChain(null)); }, [underlying]);
  useEffect(() => { loadPositions(); }, [loadPositions]);

  return (
    <div className="opt">
      <div className="opt-head">
        <h1>Options</h1>
        <p className="opt-sub">European calls & puts, cash-settled in USDT. Buy the right, not the obligation.</p>
      </div>

      <div className="opt-coins">
        {COINS.map((c) => <button key={c} className={c === underlying ? "on" : ""} onClick={() => setUnderlying(c)}>{c}</button>)}
        {chain && <span className="opt-spot">Spot ${Number(chain.spot).toLocaleString()}</span>}
      </div>

      <div className="opt-grid">
        {kycOk === false ? <div className="opt-card"><KycRequiredNotice /></div> :
          chain && <BuyForm chain={chain} onBought={loadPositions} />}
        <Positions positions={positions} />
      </div>
    </div>
  );
}

function BuyForm({ chain, onBought }: { chain: OptionChain; onBought: () => void }) {
  const [type, setType] = useState<"CALL" | "PUT">("CALL");
  const [expiry, setExpiry] = useState(chain.expiries[0]);
  const [strike, setStrike] = useState(chain.strikes[Math.floor(chain.strikes.length / 2)]);
  const [size, setSize] = useState("1");
  const [premium, setPremium] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => { setExpiry(chain.expiries[0]); setStrike(chain.strikes[Math.floor(chain.strikes.length / 2)]); }, [chain]);

  const sel = { underlying: chain.underlying, type, strike, expiry, size };
  useEffect(() => {
    if (!size || Number(size) <= 0) { setPremium(null); return; }
    let live = true;
    api.optionsQuote(sel).then((q) => live && setPremium(q.total_premium)).catch(() => live && setPremium(null));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, strike, expiry, size, chain.underlying]);

  async function buy() {
    setBusy(true); setNote(null);
    try {
      const o = await api.optionsBuy(sel);
      setNote(`Bought — premium ${trimAmount(o.premium_paid)} USDT`);
      onBought();
    } catch (e) { setNote(e instanceof ApiError ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <div className="opt-card">
      <h2>Buy option</h2>
      <div className="opt-seg">
        <button className={type === "CALL" ? "call on" : "call"} onClick={() => setType("CALL")}>Call (up)</button>
        <button className={type === "PUT" ? "put on" : "put"} onClick={() => setType("PUT")}>Put (down)</button>
      </div>
      <label className="opt-field">Expiry
        <select value={expiry} onChange={(e) => setExpiry(e.target.value)}>
          {chain.expiries.map((e) => <option key={e} value={e}>{new Date(e).toLocaleDateString(undefined, { day: "numeric", month: "short", hour: "2-digit" })}</option>)}
        </select>
      </label>
      <label className="opt-field">Strike (USDT)
        <select value={strike} onChange={(e) => setStrike(e.target.value)}>
          {chain.strikes.map((s) => <option key={s} value={s}>{Number(s).toLocaleString()}</option>)}
        </select>
      </label>
      <label className="opt-field">Size ({chain.underlying})
        <input value={size} onChange={(e) => setSize(e.target.value)} inputMode="decimal" />
      </label>
      <div className="opt-premium">Premium <b>{premium ? `${trimAmount(premium)} USDT` : "…"}</b></div>
      <button className={`opt-buy ${type.toLowerCase()}`} disabled={busy || !premium} onClick={buy}>{busy ? "…" : `Buy ${type}`}</button>
      {note && <p className="opt-note">{note}</p>}
    </div>
  );
}

function Positions({ positions }: { positions: OptionPosition[] }) {
  return (
    <div className="opt-card">
      <h2>My options</h2>
      {positions.length === 0 && <p className="opt-empty">No options yet.</p>}
      {positions.map((p) => {
        const itm = p.mark && (p.type === "CALL" ? Number(p.mark) > Number(p.strike) : Number(p.mark) < Number(p.strike));
        return (
          <div className="opt-pos" key={p.id}>
            <div className="opt-pos-top">
              <span className={`opt-badge ${p.type.toLowerCase()}`}>{p.type}</span>
              <b>{p.underlying} {Number(p.strike).toLocaleString()}</b>
              <span className={`opt-status s-${p.status.toLowerCase()}`}>{p.status.toLowerCase()}</span>
            </div>
            <div className="opt-pos-meta">
              {trimAmount(p.size)} · premium {trimAmount(p.premium_paid)} USDT · exp {new Date(p.expiry).toLocaleDateString()}
              {p.status === "OPEN" && p.mark && <span className={itm ? "up" : "down"}> · mark {Number(p.mark).toLocaleString()} ({itm ? "ITM" : "OTM"})</span>}
              {p.status !== "OPEN" && <span className={Number(p.payout) > 0 ? "up" : "down"}> · payout {trimAmount(p.payout)} USDT</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
