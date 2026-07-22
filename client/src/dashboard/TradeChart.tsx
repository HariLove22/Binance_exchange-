import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { api, type Kline } from "../lib/api";

/**
 * Candles from Binance's public feed (proxied through our API), via lightweight-charts —
 * TradingView's own open-source library. The chart is reference price history: context for a
 * trade, not our book. Our book is the order-book panel beside it.
 *
 * The chart lives outside React's render cycle — it owns a canvas and mutates in place, so
 * re-rendering it through props would throw away the user's zoom and pan. React creates it once;
 * data goes in imperatively.
 */
export function TradeChart({ symbol, interval }: { symbol: string; interval: string }) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!host.current) return;
    const c = createChart(host.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#848e9c", attributionLogo: false },
      grid: { vertLines: { color: "rgba(148,163,184,0.08)" }, horzLines: { color: "rgba(148,163,184,0.08)" } },
      rightPriceScale: { borderColor: "rgba(148,163,184,0.15)" },
      timeScale: { borderColor: "rgba(148,163,184,0.15)", timeVisible: true, secondsVisible: false },
    });
    series.current = c.addSeries(CandlestickSeries, {
      upColor: "#0ecb81", downColor: "#f6465d", borderVisible: false,
      wickUpColor: "#0ecb81", wickDownColor: "#f6465d",
    });
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.klines(symbol, interval, 300).then((rows: Kline[]) => {
      if (cancelled || !series.current) return;
      series.current.setData(
        rows.map((k) => ({
          time: (k[0] / 1000) as UTCTimestamp,
          open: Number(k[1]), high: Number(k[2]), low: Number(k[3]), close: Number(k[4]),
        })),
      );
      chart.current?.timeScale().fitContent();
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [symbol, interval]);

  return <div className="trade-chart" ref={host} />;
}
