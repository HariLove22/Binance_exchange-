import { useEffect, useState } from "react";
import { IconArrow, IconCheck } from "./Icons";
import { navigate } from "../../router";

// A compact, animated "order book" visual for the hero — pure decoration, but it
// signals what the product is at a glance.
function useBook() {
  const [seed, setSeed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeed((s) => s + 1), 1200);
    return () => clearInterval(id);
  }, []);
  const rows = (side: "ask" | "bid") =>
    Array.from({ length: 5 }, (_, i) => {
      const base = side === "ask" ? 67440 + i * 6 : 67420 - i * 6;
      const jitter = ((seed + i) % 3) * 0.7;
      const size = 20 + ((seed * 7 + i * 13) % 70);
      return { price: base + jitter, size };
    });
  return { asks: rows("ask"), bids: rows("bid") };
}

export function Hero() {
  const { asks, bids } = useBook();

  return (
    <section className="hero" id="top">
      <div className="hero-glow" aria-hidden />
      <div className="hero-inner">
        <div className="hero-copy">
          <span className="pill">
            <span className="pill-dot" /> Now in early access — India
          </span>
          <h1>
            Trade crypto with a<br />
            <span className="grad">ledger you can trust</span>
          </h1>
          <p className="lede">
            A spot exchange built on integer-exact accounting and a deterministic matching engine.
            Fast fills, transparent fees, and every rupee reconciled — down to the satoshi.
          </p>

          <div className="hero-cta">
            <button className="btn btn-primary btn-lg" onClick={() => navigate("signup")}>
              Start trading <IconArrow className="ic" />
            </button>
            <a className="btn btn-outline btn-lg" href="#markets">
              View markets
            </a>
          </div>

          <ul className="hero-checks">
            <li>
              <IconCheck className="ic" /> No hidden spread
            </li>
            <li>
              <IconCheck className="ic" /> INR via UPI escrow
            </li>
            <li>
              <IconCheck className="ic" /> Non-custodial roadmap
            </li>
          </ul>
        </div>

        <div className="hero-visual">
          <div className="book-card">
            <div className="book-head">
              <span className="coin-chip lg" style={{ background: "#F7931A22", color: "#F7931A" }}>
                ₿
              </span>
              <div>
                <strong>BTC/USDT</strong>
                <em className="up">$67,432.18 · +2.41%</em>
              </div>
              <span className="book-badge">Order book</span>
            </div>

            <div className="book-body">
              {asks.map((r, i) => (
                <div className="book-line ask" key={`a${i}`}>
                  <span className="bar" style={{ width: `${r.size}%` }} />
                  <span className="bp mono">{r.price.toFixed(2)}</span>
                  <span className="bs mono">{(r.size / 100 + 0.02).toFixed(3)}</span>
                </div>
              ))}
              <div className="book-mid mono">
                67,432.18 <span className="up">▲</span>
              </div>
              {bids.map((r, i) => (
                <div className="book-line bid" key={`b${i}`}>
                  <span className="bar" style={{ width: `${r.size}%` }} />
                  <span className="bp mono">{r.price.toFixed(2)}</span>
                  <span className="bs mono">{(r.size / 100 + 0.02).toFixed(3)}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="visual-glow" aria-hidden />
        </div>
      </div>
    </section>
  );
}
