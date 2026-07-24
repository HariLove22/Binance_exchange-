import { useState } from "react";
import { OrderBook } from "./OrderBook";
import { OrderForm } from "./OrderForm";

const PAIR = "BTC/USDT";

export function Orders() {
  // Bumped after a successful order so the book refetches and shows it.
  const [refreshToken, setRefreshToken] = useState(0);
  // Price clicked in the book, handed to the form.
  const [presetPrice, setPresetPrice] = useState<string>();

  return (
    <div>
      <div className="page-head">
        <h1>Orders</h1>
        <span className="pair-chip">{PAIR}</span>
      </div>

      <div className="trade-grid">
        <OrderBook pair={PAIR} refreshToken={refreshToken} onPriceClick={setPresetPrice} />
        <OrderForm
          pair={PAIR}
          presetPrice={presetPrice}
          onPlaced={() => setRefreshToken((n) => n + 1)}
        />
      </div>
    </div>
  );
}
