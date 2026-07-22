import { useEffect, useRef, useState } from "react";
import { subscribeTickers, type Ticker } from "./liveFeed";

/**
 * Live tickers for a set of symbols, as a { SYMBOL: Ticker } map that re-renders on each tick.
 *
 * The symbol set is joined into a string dependency so passing a fresh array each render does not
 * re-subscribe on every render — only when the actual set of symbols changes.
 */
export function useTickers(symbols: string[]): Record<string, Ticker> {
  const key = symbols.slice().sort().join(",");
  const [tickers, setTickers] = useState<Record<string, Ticker>>({});

  useEffect(() => {
    if (!key) return;
    const list = key.split(",");
    const unsub = subscribeTickers(list, (t) => {
      setTickers((prev) => (prev[t.symbol]?.price === t.price && prev[t.symbol]?.changePercent === t.changePercent ? prev : { ...prev, [t.symbol]: t }));
    });
    return unsub;
  }, [key]);

  return tickers;
}

/** A single live ticker, or null until the first tick. */
export function useTicker(symbol: string): Ticker | null {
  const map = useTickers(symbol ? [symbol] : []);
  return map[symbol] ?? null;
}

/** A ref-backed callback that always sees the latest closure without re-subscribing. */
export function useLatest<T>(value: T) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}
