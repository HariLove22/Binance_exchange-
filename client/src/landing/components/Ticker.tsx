import { useEffect, useState } from "react";
import { MARKETS, type Market } from "../data";

// Client-side price simulation so the board feels alive before a real market feed
// exists. A gentle random walk on the seed prices — replace with a WS subscription later.
function useLivePrices(): Market[] {
  const [markets, setMarkets] = useState<Market[]>(MARKETS);

  useEffect(() => {
    const id = setInterval(() => {
      setMarkets((prev) =>
        prev.map((m) => {
          const drift = (Math.random() - 0.5) * 0.004; // ±0.2%
          const price = m.price * (1 + drift);
          const change = m.change + drift * 100;
          return { ...m, price, change };
        }),
      );
    }, 1600);
    return () => clearInterval(id);
  }, []);

  return markets;
}

function fmtPrice(p: number): string {
  if (p >= 100) return p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return p.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

export function MarketBoard() {
  const markets = useLivePrices();

  return (
    <section className="section" id="markets">
      <div className="section-head">
        <h2>Live markets</h2>
        <p>Prices update in real time. Spot pairs, no leverage games.</p>
      </div>

      <div className="market-table">
        <div className="market-row market-head">
          <span>Pair</span>
          <span className="ta-right">Price</span>
          <span className="ta-right">24h</span>
          <span className="ta-right hide-sm">Chart</span>
          <span className="ta-right hide-sm">Trade</span>
        </div>

        {markets.map((m) => {
          const up = m.change >= 0;
          return (
            <div className="market-row" key={m.symbol}>
              <span className="market-pair">
                <span className="coin-chip" style={{ background: `${m.color}22`, color: m.color }}>
                  {m.icon}
                </span>
                <span>
                  <strong>{m.symbol}</strong>
                  <em>{m.name}</em>
                </span>
              </span>
              <span className="ta-right mono">${fmtPrice(m.price)}</span>
              <span className={`ta-right mono ${up ? "up" : "down"}`}>
                {up ? "▲" : "▼"} {Math.abs(m.change).toFixed(2)}%
              </span>
              <span className="ta-right hide-sm">
                <Spark up={up} />
              </span>
              <span className="ta-right hide-sm">
                <button className="btn btn-mini">Trade</button>
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// A tiny decorative sparkline. Deterministic per-direction so it doesn't jump each render.
function Spark({ up }: { up: boolean }) {
  const points = up ? "0,14 8,10 16,12 24,6 32,8 40,2" : "0,4 8,7 16,5 24,10 32,8 40,14";
  return (
    <svg width="40" height="16" viewBox="0 0 40 16" className={up ? "spark up" : "spark down"}>
      <polyline points={points} fill="none" strokeWidth="1.5" />
    </svg>
  );
}
