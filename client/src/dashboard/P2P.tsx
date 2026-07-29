import { useEffect, useState, useCallback, useRef } from "react";
import { api, ApiError, type P2PAd, type P2POrder } from "../lib/api";
import "./p2p.css";

// Coin strip like Binance's. Browsing a coin with no ads just shows an empty state.
const COINS = ["USDT", "BTC", "USDC", "FDUSD", "BNB", "ETH", "TRX", "SHIB", "XRP", "SOL", "DOGE", "PEPE"];
const FIATS = ["INR", "USD", "EUR", "GBP", "AED", "SGD"];
const PAYMENTS = ["All payment methods", "UPI", "IMPS", "BANK", "WISE", "PAYPAL"];

type View = "market" | "myads";

/**
 * P2P: buy and sell crypto for fiat directly with other users, escrow-protected. Modeled on
 * Binance's P2P surface — a Buy/Sell toggle, a coin strip, filters (amount, payment, sort), and an
 * advertiser-rich ad list. A "Buy" intent is served by SELL ads and vice versa. Opening an order
 * escrows the seller's crypto; the buyer pays fiat off-platform, marks paid, the seller releases.
 */
export function P2P() {
  const [view, setView] = useState<View>("market");
  const [tab, setTab] = useState<"BUY" | "SELL">("BUY");
  const [coin, setCoin] = useState("USDT");
  const [fiat, setFiat] = useState("INR");
  const [amount, setAmount] = useState("");
  const [payment, setPayment] = useState(PAYMENTS[0]);
  const [sort, setSort] = useState<"price" | "recent">("price");
  const [ads, setAds] = useState<P2PAd[]>([]);
  const [orders, setOrders] = useState<P2POrder[]>([]);
  const [showPost, setShowPost] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const moreRef = useRef<HTMLDivElement>(null);

  const adSide = tab === "BUY" ? "SELL" : "BUY";

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) setMoreOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const loadAds = useCallback(async () => {
    setErr(null);
    try {
      if (view === "myads") {
        setAds(await api.p2pMyAds());
      } else {
        setAds(await api.p2pAds({
          asset: coin, fiat, side: adSide, sort,
          amount: amount || undefined,
          payment_method: payment === PAYMENTS[0] ? undefined : payment,
        }));
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  }, [view, coin, fiat, adSide, sort, amount, payment]);

  const loadOrders = useCallback(async () => {
    try { setOrders(await api.p2pMyOrders()); } catch { /* secondary */ }
  }, []);

  useEffect(() => { loadAds(); }, [loadAds]);
  useEffect(() => { loadOrders(); }, [loadOrders]);

  const refresh = () => { loadAds(); loadOrders(); };

  return (
    <div className="p2p">
      {/* sub-nav: Express | P2P | Block, plus P2P actions on the right */}
      <div className="p2p-subnav">
        <div className="p2p-subtabs">
          <button className="on">P2P</button>
        </div>
        <div className="p2p-subactions">
          <button className={view === "market" ? "on" : ""} onClick={() => setView("market")}>Market</button>
          <button className={view === "myads" ? "on" : ""} onClick={() => { setView("myads"); }}>Orders &amp; Ads</button>
          <div className="p2p-more" ref={moreRef}>
            <button onClick={() => setMoreOpen((o) => !o)}>More ▾</button>
            {moreOpen && (
              <div className="p2p-more-menu">
                <button onClick={() => { setShowPost(true); setMoreOpen(false); }}>+ Post new Ad</button>
                <button onClick={() => { setView("myads"); setMoreOpen(false); }}>My ads</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {showPost && <PostAdForm defaultCoin={coin} defaultFiat={fiat} onDone={() => { setShowPost(false); refresh(); }} onClose={() => setShowPost(false)} />}

      {view === "market" && (
        <>
          <div className="p2p-toolbar">
            <div className="p2p-bs">
              <button className={tab === "BUY" ? "buy on" : "buy"} onClick={() => setTab("BUY")}>Buy</button>
              <button className={tab === "SELL" ? "sell on" : "sell"} onClick={() => setTab("SELL")}>Sell</button>
            </div>
            <div className="p2p-coins">
              {COINS.map((c) => (
                <button key={c} className={c === coin ? "on" : ""} onClick={() => setCoin(c)}>
                  {c}{c === "USDT" && <span className="p2p-apr">31.49% APR</span>}
                </button>
              ))}
            </div>
          </div>

          <div className="p2p-filters">
            <div className="p2p-amount">
              <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" placeholder="Transaction amount" />
              <select value={fiat} onChange={(e) => setFiat(e.target.value)} className="p2p-fiatsel">
                {FIATS.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
            <select value={payment} onChange={(e) => setPayment(e.target.value)} className="p2p-paysel">
              {PAYMENTS.map((p) => <option key={p}>{p}</option>)}
            </select>
            <button className="p2p-refresh" onClick={refresh}>↻ Refresh</button>
            <label className="p2p-sort">Sort By
              <select value={sort} onChange={(e) => setSort(e.target.value as "price" | "recent")}>
                <option value="price">Price</option>
                <option value="recent">Newest</option>
              </select>
            </label>
          </div>
        </>
      )}

      {err && <p className="p2p-err">{err}</p>}

      <div className="p2p-ads">
        <div className="p2p-ads-h">
          <span>Advertiser</span><span>Price</span><span>Available / Order Limit</span>
          <span>Payment</span><span className="ta-r">{view === "myads" ? "Manage" : "Trade"}</span>
        </div>
        {ads.length === 0 && (
          <p className="p2p-empty">
            {view === "myads" ? "You have no ads yet. Post one from the More menu." : `No ads for ${coin}/${fiat}. Try another coin or post one.`}
          </p>
        )}
        {ads.map((ad) => view === "myads"
          ? <MyAdRow key={ad.id} ad={ad} onDone={refresh} onErr={setErr} />
          : <AdRow key={ad.id} ad={ad} tab={tab} onDone={refresh} onErr={setErr} />
        )}
      </div>

      <MyOrders orders={orders} onDone={refresh} />
    </div>
  );
}

function Advertiser({ ad }: { ad: P2PAd }) {
  return (
    <span className="p2p-adv">
      <span className="p2p-avatar">{ad.maker_name[0]?.toUpperCase()}<i className="p2p-online" /></span>
      <span className="p2p-adv-body">
        <span className="p2p-adv-name">{ad.maker_name} <span className="p2p-badge" title="Verified merchant">◆</span></span>
        <span className="p2p-adv-stats">
          {ad.maker_orders > 0
            ? <>{ad.maker_orders.toLocaleString()} orders <span className="dot">·</span> {ad.maker_completion}% completion</>
            : <span className="p2p-new">New advertiser</span>}
        </span>
        <span className="p2p-adv-meta">👍 {ad.maker_completion ?? "—"}% <span className="dot">·</span> ⏱ {ad.pay_window_min} min</span>
      </span>
    </span>
  );
}

function PayChips({ methods }: { methods: string[] }) {
  return (
    <span className="p2p-pm">
      {methods.map((m) => <span key={m} className="p2p-chip"><i />{m}</span>)}
    </span>
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
      setOpen(false); setFiatAmt(""); onDone();
    } catch (e) {
      onErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  const crypto = Number(fiatAmt) > 0 && Number(ad.price) > 0 ? (Number(fiatAmt) / Number(ad.price)).toFixed(6) : "0";

  return (
    <div className="p2p-ad">
      <div className="p2p-ad-row">
        <Advertiser ad={ad} />
        <span className="p2p-price">{Number(ad.price).toLocaleString(undefined, { maximumFractionDigits: 4 })} <em>{ad.fiat}</em></span>
        <span className="p2p-avail">
          <span className="mono">{Number(ad.available_qty).toLocaleString()} {ad.asset}</span>
          <em>{Number(ad.min_fiat).toLocaleString()} – {Number(ad.max_fiat).toLocaleString()} {ad.fiat}</em>
        </span>
        <PayChips methods={ad.payment_methods} />
        <span className="ta-r">
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

function MyAdRow({ ad, onDone, onErr }: { ad: P2PAd; onDone: () => void; onErr: (s: string) => void }) {
  const [busy, setBusy] = useState(false);
  async function close() {
    setBusy(true);
    try { await api.p2pCloseAd(ad.id); onDone(); }
    catch (e) { onErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return (
    <div className="p2p-ad">
      <div className="p2p-ad-row">
        <span className={`p2p-side ${ad.side === "SELL" ? "sell" : "buy"}`}>{ad.side}</span>
        <span className="p2p-price">{Number(ad.price).toLocaleString()} <em>{ad.fiat}</em></span>
        <span className="p2p-avail">
          <span className="mono">{Number(ad.available_qty).toLocaleString()} {ad.asset}</span>
          <em>{Number(ad.min_fiat).toLocaleString()} – {Number(ad.max_fiat).toLocaleString()} {ad.fiat}</em>
        </span>
        <PayChips methods={ad.payment_methods} />
        <span className="ta-r"><button className="p2p-mini" disabled={busy} onClick={close}>Close</button></span>
      </div>
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
              {o.status === "PENDING_PAYMENT" && iAmBuyer && <button className="p2p-mini buy" onClick={() => act(() => api.p2pMarkPaid(o.id))}>I've paid</button>}
              {o.status === "PENDING_PAYMENT" && <button className="p2p-mini" onClick={() => act(() => api.p2pCancel(o.id))}>Cancel</button>}
              {o.status === "PAID" && iAmSeller && <button className="p2p-mini buy" onClick={() => act(() => api.p2pRelease(o.id))}>Release</button>}
              {o.status === "PAID" && <button className="p2p-mini warn" onClick={() => act(() => api.p2pDispute(o.id))}>Dispute</button>}
              {o.status === "DISPUTED" && <span className="dim">under review</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function PostAdForm({ defaultCoin, defaultFiat, onDone, onClose }: { defaultCoin: string; defaultFiat: string; onDone: () => void; onClose: () => void }) {
  const [side, setSide] = useState<"BUY" | "SELL">("SELL");
  const [asset, setAsset] = useState(defaultCoin);
  const [fiat, setFiat] = useState(defaultFiat);
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
    setBusy(true); setErr(null);
    try {
      await api.p2pPostAd({ side, asset, fiat, price, min_fiat: minFiat, max_fiat: maxFiat, total_qty: qty, payment_methods: methods, terms: terms || null });
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="p2p-modal" onClick={onClose}>
      <form className="p2p-postform" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <div className="p2p-pf-head"><h3>Post a new Ad</h3><button type="button" className="p2p-x" onClick={onClose}>✕</button></div>
        <div className="p2p-pf-grid">
          <label>I want to
            <div className="p2p-bs sm">
              <button type="button" className={side === "SELL" ? "sell on" : "sell"} onClick={() => setSide("SELL")}>Sell</button>
              <button type="button" className={side === "BUY" ? "buy on" : "buy"} onClick={() => setSide("BUY")}>Buy</button>
            </div>
          </label>
          <label>Coin<select value={asset} onChange={(e) => setAsset(e.target.value)}>{COINS.map((a) => <option key={a}>{a}</option>)}</select></label>
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
    </div>
  );
}
