import { useEffect, useState } from "react";
import { api } from "./api";

/**
 * The full list of USDT-quoted coins, from the live market universe (Binance exchangeInfo, TRADING
 * only — already fetched and filtered server-side by /market/all). Volume-sorted, so the busiest
 * coins sit at the top like a real exchange.
 *
 * `tradeable` is the subset we actually custody: buy/convert works for those; the rest are shown
 * for browsing but flagged. Cached at module scope so switching tabs doesn't refetch.
 */

const FALLBACK = ["USDT", "USDC", "BTC", "ETH", "SOL", "BNB", "AVAX", "POL", "TRX"];

let cache: { coins: string[]; tradeable: Set<string> } | null = null;

export function useCoins(): { coins: string[]; tradeable: Set<string> } {
  const [state, setState] = useState(cache ?? { coins: FALLBACK, tradeable: new Set(FALLBACK) });

  useEffect(() => {
    if (cache) return;
    api
      .marketUniverse("USDT")
      .then((u) => {
        const tradeable = new Set<string>(["USDT"]);
        const coins: string[] = ["USDT"];
        const seen = new Set<string>(["USDT"]);
        for (const m of u.markets) {
          if (seen.has(m.base)) continue;
          seen.add(m.base);
          coins.push(m.base);
          if (m.tradeable) tradeable.add(m.base);
        }
        cache = { coins, tradeable };
        setState(cache);
      })
      .catch(() => {
        cache = { coins: FALLBACK, tradeable: new Set(FALLBACK) };
        setState(cache);
      });
  }, []);

  return state;
}
