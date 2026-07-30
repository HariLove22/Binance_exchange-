import { useState } from "react";
import { OrderBook } from "./OrderBook";
import { OrderForm } from "./OrderForm";
import { MyOrders } from "./MyOrders";
import { useCoins } from "../lib/useCoins";

export function Orders() {
  const { coins, tradeable } = useCoins();
  // Bumped after any order change (place / cancel). The order book updates itself over WebSocket,
  // so this only drives the parts that read REST: the form's balance, open orders, and history.
  const [refreshToken, setRefreshToken] = useState(0);
  const bump = () => setRefreshToken((n) => n + 1);
  // Price clicked in the book, handed to the form.
  const [presetPrice, setPresetPrice] = useState<string>();

  // The coin being traded (always against USDT). The coin picker lives in the order form's amount
  // field. Every USDT coin is pickable; only the ones we custody are tradeable — the rest still
  // show a live chart/book, but the form goes view-only.
  const [base, setBase] = useState("BTC");
  const pair = `${base}/USDT`;
  const isTradeable = tradeable.has(base);
  const baseOptions = coins.filter((c) => c !== "USDT"); // can't trade USDT against itself

  return (
    <div>
      <div className="page-head">
        <h1>Orders</h1>
      </div>

      <div className="trade-grid">
        <OrderBook pair={pair} tradeable={isTradeable} refreshToken={refreshToken} onPriceClick={setPresetPrice} />
        <OrderForm
          pair={pair}
          presetPrice={presetPrice}
          refreshToken={refreshToken}
          tradeable={isTradeable}
          coins={{ list: baseOptions, tradeable }}
          onBaseChange={setBase}
          onPlaced={bump}
        />
      </div>

      {/* One tabbed panel: Open (cancellable) · Filled · Cancelled. Placing or cancelling an order
          bumps refreshToken so the list and the form's balance refresh; the book updates live. */}
      <MyOrders refreshToken={refreshToken} onChanged={bump} />
    </div>
  );
}
