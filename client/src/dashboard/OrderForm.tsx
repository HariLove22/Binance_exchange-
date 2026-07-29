import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, trimAmount, type Balance, type OrderRow } from "../lib/api";
import {
  fromUnits,
  isPositive,
  multiply,
  product,
  sumProducts,
  toUnits,
  trimZeros,
  withThousands,
} from "../lib/amount";
import { CoinSelect } from "./CoinSelect";

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
  refreshToken = 0,
  tradeable = true,
  coins,
  onBaseChange,
  onPlaced,
}: {
  pair?: string;
  /** Price clicked in the order book — fills the field. */
  presetPrice?: string;
  /** Bump to refetch the balance (e.g. after an order is placed or cancelled elsewhere). */
  refreshToken?: number;
  /** False for a coin we don't run a market for — the form goes read-only (browse, not trade). */
  tradeable?: boolean;
  /** All selectable base coins + which are custodied — powers the coin picker in the amount field. */
  coins?: { list: string[]; tradeable: Set<string> };
  /** Called when the user picks a different base coin from the amount-field dropdown. */
  onBaseChange?: (base: string) => void;
  onPlaced?: () => void;
}) {
  const [base, quote] = pair.split("/");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<OrderRow | null>(null);
  const [balances, setBalances] = useState<Balance[] | null>(null);

  useEffect(() => {
    if (presetPrice) setPrice(sanitizeAmount(presetPrice));
  }, [presetPrice]);

  // The balance the user is about to spend: quote (USDT) to buy, base (BTC) to sell. Shown so they
  // know their limit up front instead of discovering it as an "insufficient funds" error.
  useEffect(() => {
    let alive = true;
    api
      .balances()
      .then((b) => alive && setBalances(b))
      .catch(() => alive && setBalances([]));
    return () => {
      alive = false;
    };
  }, [refreshToken]);

  const spendAsset = side === "BUY" ? quote : base;
  const spendAvail = balances?.find((b) => b.asset === spendAsset)?.available ?? null;

  /** Fill quantity with the most the balance allows. Selling: all the base. Buying: quote / price. */
  function fillMax() {
    if (spendAvail === null) return;
    if (side === "SELL") {
      setQuantity(spendAvail);
      return;
    }
    if (!isPositive(price)) {
      setError("Enter a price first to compute the max quantity");
      return;
    }
    // maxQty = availableQuote / price, truncated to SCALE — floors, so it never exceeds the balance.
    const maxUnits = (toUnits(spendAvail, SCALE) * 10n ** BigInt(SCALE)) / toUnits(price, SCALE);
    setQuantity(fromUnits(maxUnits, SCALE));
  }

  const valid = isPositive(price) && isPositive(quantity);
  // Preview only — the server computes the real numbers.
  const total = valid ? multiply(price, quantity, SCALE) : "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);

    if (!tradeable) return setError(`${base} isn't tradeable here yet — view only`);
    if (!isPositive(price)) return setError("Enter a price greater than zero");
    if (!isPositive(quantity)) return setError("Enter a quantity greater than zero");

    setBusy(true);
    try {
      // The order book / matching engine speaks in symbols ("BTCUSDT"); the form in pairs.
      const res = await api.placeOrder({
        symbol: pair.replace("/", "").toUpperCase(),
        side,
        type: "LIMIT",
        quantity,
        price,
      });
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

      <div className="of-avail">
        <span>Available</span>
        <button type="button" className="of-avail-val" onClick={fillMax} title="Use max">
          {spendAvail === null ? "…" : `${trimAmount(spendAvail)} ${spendAsset}`}
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
          <em>{quote}</em>
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
          {coins && onBaseChange ? (
            <CoinSelect
              value={base}
              options={coins.list}
              tradeable={coins.tradeable}
              onChange={onBaseChange}
            />
          ) : (
            <em>{base}</em>
          )}
        </div>
      </label>

      <div className="of-total">
        <span>Total</span>
        <strong>{total ? `${withThousands(total)} ${quote}` : "—"}</strong>
      </div>

      {/* Not disabled on invalid input — a dead button with no explanation reads as "the app
          is broken". Let the click through and say what's missing. */}
      <button
        className={`of-submit ${side.toLowerCase()}`}
        type="submit"
        disabled={busy || !tradeable}
      >
        {!tradeable ? "View only" : busy ? "Placing…" : `${side === "BUY" ? "Buy" : "Sell"} ${base}`}
      </button>

      {!tradeable ? (
        <div className="of-msg hint">
          {base} isn't custodied here yet — chart &amp; book are view-only.
        </div>
      ) : !valid && !error ? (
        <div className="of-msg hint">
          {!isPositive(price)
            ? "Enter a price to continue"
            : "Enter a quantity to continue"}
        </div>
      ) : null}

      {error && <div className="of-msg err">{error}</div>}

      {result && <Receipt order={result} base={base} quote={quote} />}
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
function Receipt({ order, base, quote }: { order: OrderRow; base: string; quote: string }) {
  // order.side, not the form's `side` state — the tab may have been toggled since this
  // order was placed, and the receipt must describe the order it belongs to.
  const spent = order.side === "BUY";
  const total = sumProducts(order.fills, SCALE);

  return (
    <div className="of-receipt">
      <div className="of-receipt-head">
        <strong>#{order.id}</strong>
        <span className={`of-status ${order.status.toLowerCase()}`}>{order.status}</span>
      </div>

      <div className="of-receipt-line with-amount">
        <span>
          Filled {trimZeros(order.filled_quantity, 5)} of {trimZeros(order.quantity, 5)} {base}
        </span>
        {order.fills.length > 0 && (
          <strong className="of-amount">
            <em>{spent ? "Paid" : "Received"}</em>
            {withThousands(trimZeros(total, 2))} {quote}
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
