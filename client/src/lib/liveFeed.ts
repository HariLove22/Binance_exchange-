/**
 * Live market data over Binance's public WebSocket — real-time, no API key.
 *
 * Two streams:
 *  - `@ticker`  → live last price + 24h change for a symbol (drives price headers and PnL)
 *  - `@kline_*` → the in-progress candle, so the chart's last bar updates as it forms
 *
 * One shared socket, reference-counted per stream, so ten components watching ETHUSDT open one
 * subscription, not ten. Reconnects with backoff; on reconnect it re-subscribes everything.
 *
 * This is the *datafeed* — reference prices. It is not where orders execute; those go to our
 * engine. Valuing a portfolio and drawing a chart are read-only uses of a public feed.
 */

const WS_BASE = "wss://data-stream.binance.vision/stream";

export interface Ticker {
  symbol: string; // e.g. ETHUSDT
  price: number; // last
  changePercent: number; // 24h
  high: number;
  low: number;
  quoteVolume: number;
}

export interface LiveCandle {
  time: number; // seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  isClosed: boolean;
}

/**
 * Candle history straight from Binance's public REST, no proxy hop — the fastest path, and the
 * host allows cross-origin reads (`Access-Control-Allow-Origin: *`). Returns oldest-first, which
 * is what the chart wants.
 */
const REST_BASE = "https://data-api.binance.vision/api/v3";

export async function fetchKlines(symbol: string, interval: string, limit = 500): Promise<LiveCandle[]> {
  const url = `${REST_BASE}/klines?symbol=${symbol.toUpperCase()}&interval=${interval}&limit=${limit}`;
  const rows = (await (await fetch(url)).json()) as unknown[][];
  return rows.map((k) => ({
    time: Number(k[0]) / 1000,
    open: Number(k[1]),
    high: Number(k[2]),
    low: Number(k[3]),
    close: Number(k[4]),
    volume: Number(k[5]),
    isClosed: true,
  }));
}

type Listener = (data: unknown) => void;

class FeedManager {
  private ws: WebSocket | null = null;
  private streams = new Map<string, Set<Listener>>();
  private retries = 0;

  subscribe(stream: string, listener: Listener): () => void {
    let set = this.streams.get(stream);
    const isNew = !set;
    if (!set) {
      set = new Set();
      this.streams.set(stream, set);
    }
    set.add(listener);

    if (!this.ws) this.connect();
    else if (isNew && this.ws.readyState === WebSocket.OPEN) this.send("SUBSCRIBE", [stream]);

    return () => {
      const s = this.streams.get(stream);
      if (!s) return;
      s.delete(listener);
      if (s.size === 0) {
        this.streams.delete(stream);
        if (this.ws?.readyState === WebSocket.OPEN) this.send("UNSUBSCRIBE", [stream]);
      }
    };
  }

  private connect() {
    this.ws = new WebSocket(WS_BASE);

    this.ws.onopen = () => {
      this.retries = 0;
      const all = [...this.streams.keys()];
      if (all.length) this.send("SUBSCRIBE", all);
    };

    this.ws.onmessage = (ev) => {
      let frame: { stream?: string; data?: unknown };
      try {
        frame = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      if (!frame.stream) return;
      const set = this.streams.get(frame.stream);
      if (set) set.forEach((l) => l(frame.data));
    };

    this.ws.onclose = () => {
      this.ws = null;
      if (this.streams.size === 0) return;
      // Backoff, capped. A tight reconnect loop against a rate-limited host earns a ban.
      const delay = Math.min(1000 * 2 ** this.retries, 15000);
      this.retries++;
      setTimeout(() => this.connect(), delay);
    };

    this.ws.onerror = () => this.ws?.close();
  }

  private send(method: "SUBSCRIBE" | "UNSUBSCRIBE", params: string[]) {
    this.ws?.send(JSON.stringify({ method, params, id: Date.now() }));
  }
}

const manager = new FeedManager();

/** Subscribe to live tickers for a set of symbols. Returns an unsubscribe. */
export function subscribeTickers(symbols: string[], onTick: (t: Ticker) => void): () => void {
  const unsubs = symbols.map((symbol) =>
    manager.subscribe(`${symbol.toLowerCase()}@ticker`, (data) => {
      const d = data as Record<string, string>;
      onTick({
        symbol: d.s,
        price: Number(d.c),
        changePercent: Number(d.P),
        high: Number(d.h),
        low: Number(d.l),
        quoteVolume: Number(d.q),
      });
    }),
  );
  return () => unsubs.forEach((u) => u());
}

export function subscribeCandles(symbol: string, interval: string, onCandle: (c: LiveCandle) => void): () => void {
  return manager.subscribe(`${symbol.toLowerCase()}@kline_${interval}`, (data) => {
    const k = (data as { k: Record<string, string | number | boolean> }).k;
    onCandle({
      time: Number(k.t) / 1000,
      open: Number(k.o),
      high: Number(k.h),
      low: Number(k.l),
      close: Number(k.c),
      volume: Number(k.v),
      isClosed: Boolean(k.x),
    });
  });
}
