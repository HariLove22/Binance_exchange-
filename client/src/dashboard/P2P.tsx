import { useEffect, useState, useCallback } from "react";
import { api, ApiError, type P2PAd, type P2POrder } from "../lib/api";
import "./p2p.css";

const ASSETS = ["USDT", "BTC", "ETH", "BNB"];
const FIATS = ["INR", "USD", "EUR", "GBP", "AED", "SGD"];

/**
 * P2P: buy and sell crypto for fiat directly with other users. The exchange holds the crypto in
 * escrow — it never touches the fiat, which moves bank-to-bank between the two people. A "Buy" tab
 * shows sell ads (someone selling, so you buy); "Sell" shows buy ads. Opening an order escrows the
 * seller's crypto; the buyer pays fiat off-platform, marks it paid, and the seller releases.
 */
export function P2P() {
  const [tab, setTab] = useState<"BUY" | "SELL">("BUY");
  const [asset, setAsset] = useState("USDT");
  const [fiat, setFiat] = useState("INR");
  const [ads, setAds] = useState<P2PAd[]>([]);
  const [orders, setOrders] = useState<P2POrder[]>([]);
  const [showPost, setShowPost] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // A "Buy" intent is served by SELL ads (the maker sells), and vice versa.
  const adSide = tab === "BUY" ? "SELL" : "BUY";

  const loadAds = useCallback(async () => {
    try {
      setAds(await api.p2pAds({ asset, fiat, side: adSide }));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }, [asset, fiat, adSide]);

  const loadOrders = useCallback(async () => {
    try {
      setOrders(await api.p2pMyOrders());
    } catch { /* orders are secondary; ignore transient errors */ }
  }, []);

  useEffect(() => { loadAds(); }, [loadAds]);
  useEffect(() => { loadOrders(); }, [loadOrders]);

  const refresh = () => { loadAds(); loadOrders(); };

  return (
    <div className="p2p">
      <div className="p2p-head">
        <div>
          <h1>P2P Trading</h1>
          <p className="p2p-sub">Buy &amp; sell crypto with bank transfer. Escrow-protected.</p>
        </div>
        <button className="p2p-post-btn" onClick={() => setShowPost((s) => !s)}>
          {showPost ? "Close" : "+ Post an Ad"}
        </button>
      </div>

      {showPost && <PostAdForm onDone={() => { setShowPost(false); refresh(); }} />}

      <div className="p2p-filters">
        <div className="p2p-bs">
          <button className={tab === "BUY" ? "buy on" : "buy"} onClick={() => setTab("BUY")}>Buy</button>
          <button className={tab === "SELL" ? "sell on" : "sell"} onClick={() => setTab("SELL")}>Sell</button>
        </div>
        <label>Coin
          <select value={asset} onChange={(e) => setAsset(e.target.value)}>
            {ASSETS.map((a) => <option key={a}>{a}</option>)}
          </select>
        </label>
        <label>Fiat
          <select value={fiat} onChange={(e) => setFiat(e.target.value)}>
            {FIATS.map((f) => <option key={f}>{f}</option>)}
          </select>
        </label>
        <button className="p2p-refresh" onClick={refresh}>↻</button>
      </div>

      {err && <p className="p2p-err">{err}</p>}

      <div className="p2p-ads">
        <div className="p2p-ads-h">
          <span>Advertiser</span><span className="num">Price</span><span className="num">Available / Limit</span>
          <span>Payment</span><span></span>
        </div>
        {ads.length === 0 && <p className="p2p-empty">No ads for {asset}/{fiat}. Be the first — post one.</p>}
        {ads.map((ad) => (
          <AdRow key={ad.id} ad={ad} tab={tab} onDone={refresh} onErr={setErr} />
        ))}
      </div>

      <MyOrders orders={orders} onDone={refresh} />
    </div>
  );
}

function AdRow({ ad, tab, onDone, onErr }: { ad: P2PAd; tab: "BUY" | "SELL"; onDone: () => void; onErr: (s: string) => void }) {
  const [open, setOpen] = useState(false);
  const [fiatAmt, setFiatAmt] = useState("");
  const [method, setMethod] = useState(ad.payment_methods[0] ?? "");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await api.p2pOpenOrder({ ad_id: ad.id, fiat_amount: fiatAmt, payment_method: method });
      setOpen(false);
      setFiatAmt("");
      onDone();
    } catch (e) {
      onErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const crypto = Number(fiatAmt) > 0 && Number(ad.price) > 0 ? (Number(fiatAmt) / Number(ad.price)).toFixed(6) : "0";

  return (
    <div className="p2p-ad">
      <div className="p2p-ad-row">
        <span className="p2p-adv">
          <span className="p2p-avatar">{String(ad.maker_id)[0]}</span>
          <span className="p2p-adv-name">User #{ad.maker_id}</span>
        </span>
        <span className="num p2p-price">{Number(ad.price).toLocaleString()} <em>{ad.fiat}</em></span>
        <span className="num p2p-avail">
          {Number(ad.available_qty).toLocaleString()} {ad.asset}
          <em>{Number(ad.min_fiat).toLocaleString()}–{Number(ad.max_fiat).toLocaleString()} {ad.fiat}</em>
        </span>
        <span className="p2p-pm">{ad.payment_methods.map((m) => <span key={m} className="p2p-chip">{m}</span>)}</span>
        <span>
          <button className={tab === "BUY" ? "p2p-act buy" : "p2p-act sell"} onClick={() => setOpen((o) => !o)}>
            {tab === "BUY" ? "Buy" : "Sell"} {ad.asset}
          </button>
        </span>
      </div>
      {open && (
        <div className="p2p-order-form">
          {ad.terms && <p className="p2p-terms">“{ad.terms}”</p>}
          <div className="p2p-of-row">
            <label>I want to pay
              <div className="p2p-inp"><input value={fiatAmt} onChange={(e) => setFiatAmt(e.target.value)} inputMode="decimal" placeholder={`${ad.min_fiat}–${ad.max_fiat}`} /><span>{ad.fiat}</span></div>
            </label>
            <label>Payment
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                {ad.payment_methods.map((m) => <option key={m}>{m}</option>)}
              </select>
            </label>
          </div>
          <div className="p2p-of-foot">
            <span className="p2p-recv">You receive ≈ <b>{crypto} {ad.asset}</b></span>
            <button className="p2p-confirm" disabled={busy || !fiatAmt} onClick={submit}>{busy ? "…" : "Confirm order"}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function MyOrders({ orders, onDone }: { orders: P2POrder[]; onDone: () => void }) {
  const [err, setErr] = useState<string | null>(null);

  async function act(fn: () => Promise<unknown>) {
    try { await fn(); onDone(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }

  if (orders.length === 0) return null;

  return (
    <div className="p2p-orders">
      <h2>My Orders</h2>
      {err && <p className="p2p-err">{err}</p>}
      {orders.map((o) => {
        const iAmBuyer = o.side_for_me === "BUY";
        const iAmSeller = o.side_for_me === "SELL";
        return (
          <div className="p2p-order" key={o.id}>
            <span className={`p2p-side ${o.side_for_me.toLowerCase()}`}>{o.side_for_me}</span>
            <span className="mono">{Number(o.crypto_amount)} {o.asset}</span>
            <span className="dim">for {Number(o.fiat_amount).toLocaleString()} {o.fiat} · {o.payment_method}</span>
            <span className={`p2p-status s-${o.status.toLowerCase()}`}>{o.status.replace(/_/g, " ")}</span>
            <span className="p2p-order-acts">
              {o.status === "PENDING_PAYMENT" && iAmBuyer && (
                <button className="p2p-mini buy" onClick={() => act(() => api.p2pMarkPaid(o.id))}>I've paid</button>
              )}
              {o.status === "PENDING_PAYMENT" && (
                <button className="p2p-mini" onClick={() => act(() => api.p2pCancel(o.id))}>Cancel</button>
              )}
              {o.status === "PAID" && iAmSeller && (
                <button className="p2p-mini buy" onClick={() => act(() => api.p2pRelease(o.id))}>Release</button>
              )}
              {o.status === "PAID" && (
                <button className="p2p-mini warn" onClick={() => act(() => api.p2pDispute(o.id))}>Dispute</button>
              )}
              {o.status === "DISPUTED" && <span className="dim">under review</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function PostAdForm({ onDone }: { onDone: () => void }) {
  const [side, setSide] = useState<"BUY" | "SELL">("SELL");
  const [asset, setAsset] = useState("USDT");
  const [fiat, setFiat] = useState("INR");
  const [price, setPrice] = useState("");
  const [minFiat, setMinFiat] = useState("");
  const [maxFiat, setMaxFiat] = useState("");
  const [qty, setQty] = useState("");
  const [methods, setMethods] = useState("UPI,IMPS");
  const [terms, setTerms] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.p2pPostAd({
        side, asset, fiat, price, min_fiat: minFiat, max_fiat: maxFiat,
        total_qty: qty, payment_methods: methods, terms: terms || null,
      });
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="p2p-postform" onSubmit={submit}>
      <div className="p2p-pf-grid">
        <label>I want to
          <div className="p2p-bs sm">
            <button type="button" className={side === "SELL" ? "sell on" : "sell"} onClick={() => setSide("SELL")}>Sell</button>
            <button type="button" className={side === "BUY" ? "buy on" : "buy"} onClick={() => setSide("BUY")}>Buy</button>
          </div>
        </label>
        <label>Coin<select value={asset} onChange={(e) => setAsset(e.target.value)}>{ASSETS.map((a) => <option key={a}>{a}</option>)}</select></label>
        <label>Fiat<select value={fiat} onChange={(e) => setFiat(e.target.value)}>{FIATS.map((f) => <option key={f}>{f}</option>)}</select></label>
        <label>Price ({fiat})<input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" placeholder="90" /></label>
        <label>Total {asset}<input value={qty} onChange={(e) => setQty(e.target.value)} inputMode="decimal" placeholder="100" /></label>
        <label>Min order ({fiat})<input value={minFiat} onChange={(e) => setMinFiat(e.target.value)} inputMode="decimal" placeholder="100" /></label>
        <label>Max order ({fiat})<input value={maxFiat} onChange={(e) => setMaxFiat(e.target.value)} inputMode="decimal" placeholder="9000" /></label>
        <label>Payment methods<input value={methods} onChange={(e) => setMethods(e.target.value)} placeholder="UPI,IMPS,BANK" /></label>
        <label className="wide">Terms (optional)<input value={terms} onChange={(e) => setTerms(e.target.value)} placeholder="Release within 15 min of payment" /></label>
      </div>
      {err && <p className="p2p-err">{err}</p>}
      <button className="p2p-confirm" disabled={busy}>{busy ? "…" : "Post ad"}</button>
    </form>
  );
}
