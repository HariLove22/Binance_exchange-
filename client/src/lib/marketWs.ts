import { useEffect, useState } from "react";
import type { OrderBook, TradeTick } from "./api";

/**
 * Live order book + trades for one of OUR markets, over our WebSocket. Replaces polling: the
 * server pushes a fresh snapshot on connect, on every order/trade, and on a heartbeat.
 *
 * One connection per mounted symbol; changing symbol (or passing null for a non-tradeable pair)
 * tears the old one down. Reconnects with backoff.
 */

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws") + "/api/v1/ws/market";

interface Snapshot {
  type: string;
  symbol: string;
  bids: { price: string; quantity: string }[];
  asks: { price: string; quantity: string }[];
  trades: TradeTick[];
}

export function useMarketWs(symbol: string | null): { book: OrderBook | null; trades: TradeTick[]; live: boolean } {
  const [book, setBook] = useState<OrderBook | null>(null);
  const [trades, setTrades] = useState<TradeTick[]>([]);
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!symbol) {
      setBook(null);
      setTrades([]);
      setLive(false);
      return;
    }

    let ws: WebSocket | null = null;
    let closed = false;
    let retries = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(`${WS_BASE}/${symbol}`);

      ws.onopen = () => { retries = 0; setLive(true); };
      ws.onmessage = (ev) => {
        const d = JSON.parse(ev.data as string) as Snapshot;
        if (d.type !== "snapshot") return;
        setBook({ symbol: d.symbol, bids: d.bids, asks: d.asks });
        setTrades(d.trades);
      };
      ws.onclose = () => {
        setLive(false);
        if (closed) return;
        const delay = Math.min(1000 * 2 ** retries, 10000);
        retries++;
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [symbol]);

  return { book, trades, live };
}
