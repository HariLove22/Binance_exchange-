import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { fetchKlines, subscribeCandles, type LiveCandle } from "../lib/liveFeed";

/**
 * Candles + volume from Binance's public feed, via lightweight-charts (TradingView's open-source
 * library). The chart is reference price history — context for a trade, not our book.
 *
 * History is fetched straight from Binance's REST (no proxy hop → faster), 500 candles for a full
 * view, then the live candle streams over WebSocket. The chart lives outside React's render cycle:
 * it owns a canvas and mutates in place, so re-rendering through props would throw away the user's
 * zoom and pan. React creates it once; data goes in imperatively.
 */
export function TradeChart({ symbol, interval }: { symbol: string; interval: string }) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const price = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!host.current) return;
    const c = createChart(host.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#848e9c", attributionLogo: false },
      grid: { vertLines: { color: "rgba(148,163,184,0.06)" }, horzLines: { color: "rgba(148,163,184,0.06)" } },
      rightPriceScale: { borderColor: "rgba(148,163,184,0.15)", scaleMargins: { top: 0.05, bottom: 0.25 } },
      timeScale: { borderColor: "rgba(148,163,184,0.15)", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    price.current = c.addSeries(CandlestickSeries, {
      upColor: "#0ecb81", downColor: "#f6465d", borderVisible: false,
      wickUpColor: "#0ecb81", wickDownColor: "#f6465d",
    });
    volume.current = c.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" });
    // Pin volume to the bottom fifth so it reads as context under the price.
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      price.current = null;
      volume.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unsub: (() => void) | undefined;
    setLoading(true);

    const volColor = (c: { close: number; open: number }) =>
      c.close >= c.open ? "rgba(14,203,129,0.4)" : "rgba(246,70,93,0.4)";

    fetchKlines(symbol, interval, 500).then((rows: LiveCandle[]) => {
      if (cancelled || !price.current || !volume.current) return;
      price.current.setData(rows.map((k) => ({
        time: k.time as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close,
      })));
      volume.current.setData(rows.map((k) => ({
        time: k.time as UTCTimestamp, value: k.volume, color: volColor(k),
      })));
      chart.current?.timeScale().fitContent();
      setLoading(false);

      // Live: each tick updates the in-progress candle; a closed candle arrives with a new
      // timestamp and appends. `update` handles both.
      unsub = subscribeCandles(symbol, interval, (c) => {
        const t = c.time as UTCTimestamp;
        price.current?.update({ time: t, open: c.open, high: c.high, low: c.low, close: c.close });
        volume.current?.update({ time: t, value: c.volume, color: volColor(c) });
      });
    }).catch(() => setLoading(false));

    return () => {
      cancelled = true;
      unsub?.();
    };
  }, [symbol, interval]);

  return (
    <div className="trade-chart-wrap">
      <div className="trade-chart" ref={host} />
      {loading && <div className="chart-loading">loading {symbol}…</div>}
    </div>
  );
}
