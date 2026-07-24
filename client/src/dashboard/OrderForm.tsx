import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type OrderOut } from "../lib/api";
import {
  isPositive,
  multiply,
  product,
  sumProducts,
  trimZeros,
  withThousands,
} from "../lib/amount";

const SCALE = 8; // BTC and USDT both track 8 decimals here

/**
 * Keep only digits and a single decimal point.
 *
 * People paste "50,300.00" straight off the order book, and a thousands separator would
 * otherwise fail validation with no visible reason — the button just goes dead. Strip it as
 * they type so the field self-corrects instead of silently rejecting them.
 */
function sanitizeAmount(value: string): string {
  const cleaned = value.replace(/[^\d.]/g, "");
  const dot = cleaned.indexOf(".");
  if (dot < 0) return cleaned;
  return cleaned.slice(0, dot + 1) + cleaned.slice(dot + 1).replace(/\./g, "");
}

export function OrderForm({
  pair = "BTC/USDT",
  presetPrice,
  onPlaced,
}: {
  pair?: string;
  /** Price clicked in the order book — fills the field. */
  presetPrice?: string;
  onPlaced?: () => void;
}) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<OrderOut | null>(null);

  useEffect(() => {
    if (presetPrice) setPrice(sanitizeAmount(presetPrice));
  }, [presetPrice]);

  const valid = isPositive(price) && isPositive(quantity);
  // Preview only — the server computes the real numbers.
  const total = valid ? multiply(price, quantity, SCALE) : "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);

    if (!isPositive(price)) return setError("Enter a price greater than zero");
    if (!isPositive(quantity)) return setError("Enter a quantity greater than zero");

    setBusy(true);
    try {
      const res = await api.placeOrder({ side, price, quantity, pair });
      setResult(res);
      setQuantity("");
      onPlaced?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not place the order");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="of" onSubmit={submit}>
      <div className="of-tabs">
        <button
          type="button"
          className={`of-tab buy ${side === "BUY" ? "on" : ""}`}
          onClick={() => setSide("BUY")}
        >
          Buy
        </button>
        <button
          type="button"
          className={`of-tab sell ${side === "SELL" ? "on" : ""}`}
          onClick={() => setSide("SELL")}
        >
          Sell
        </button>
      </div>

      <label className="of-field">
        <span>Price</span>
        <div className="of-input">
          <input
            value={price}
            onChange={(e) => setPrice(sanitizeAmount(e.target.value))}
            placeholder="0.00"
            inputMode="decimal"
          />
          <em>USDT</em>
        </div>
      </label>

      <label className="of-field">
        <span>Quantity</span>
        <div className="of-input">
          <input
            value={quantity}
            onChange={(e) => setQuantity(sanitizeAmount(e.target.value))}
            placeholder="0.00000000"
            inputMode="decimal"
          />
          <em>BTC</em>
        </div>
      </label>

      <div className="of-total">
        <span>Total</span>
        <strong>{total ? `${withThousands(total)} USDT` : "—"}</strong>
      </div>

      {/* Not disabled on invalid input — a dead button with no explanation reads as "the app
          is broken". Let the click through and say what's missing. */}
      <button className={`of-submit ${side.toLowerCase()}`} type="submit" disabled={busy}>
        {busy ? "Placing…" : `${side === "BUY" ? "Buy" : "Sell"} BTC`}
      </button>

      {!valid && !error && (
        <div className="of-msg hint">
          {!isPositive(price)
            ? "Enter a price to continue"
            : "Enter a quantity to continue"}
        </div>
      )}

      {error && <div className="of-msg err">{error}</div>}

      {result && <Receipt order={result} />}
    </form>
  );
}

/**
 * Execution report for a placed order — what filled, and what it cost.
 *
 * The per-fill amounts matter because a taker rarely pays its own limit price: each fill
 * trades at the *maker's* price, so an order for 3 BTC @ 50,300 that sweeps three levels
 * costs less than 3 x 50,300. The form's "Total" is the limit-price estimate; the number
 * here is what actually moved.
 */
function Receipt({ order }: { order: OrderOut }) {
  // order.side, not the form's `side` state — the tab may have been toggled since this
  // order was placed, and the receipt must describe the order it belongs to.
  const spent = order.side === "BUY";
  const total = sumProducts(order.fills, SCALE);

  return (
    <div className="of-receipt">
      <div className="of-receipt-head">
        <strong>#{order.order_id}</strong>
        <span className={`of-status ${order.status.toLowerCase()}`}>{order.status}</span>
      </div>

      <div className="of-receipt-line with-amount">
        <span>
          Filled {trimZeros(order.filled_quantity, 5)} of {trimZeros(order.quantity, 5)} BTC
        </span>
        {order.fills.length > 0 && (
          <strong className="of-amount">
            <em>{spent ? "Paid" : "Received"}</em>
            {withThousands(trimZeros(total, 2))} USDT
          </strong>
        )}
      </div>

      {order.fills.length > 0 ? (
        <ul className="of-fills">
          {order.fills.map((f, i) => (
            <li key={i}>
              <span>
                {trimZeros(f.quantity, 5)} @ {withThousands(trimZeros(f.price, 2))}
              </span>
              <span className="of-fill-amt">
                {withThousands(trimZeros(product(f.price, f.quantity, SCALE), 2))}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="of-receipt-line dim">No match — resting on the book.</div>
      )}
    </div>
  );
}
