import { useState } from "react";

/**
 * A coin's logo, from a public icon CDN, with a graceful fallback.
 *
 * The CDN (cryptocurrency-icons) covers the well-known few hundred coins; anything it lacks — a new
 * or exotic listing — falls back to a coloured letter badge so the row never renders a broken image.
 * The badge colour is derived from the symbol so the same coin always gets the same tint.
 */

const CDN = (symbol: string) =>
  `https://cdn.jsdelivr.net/npm/cryptocurrency-icons@0.18.1/128/color/${symbol.toLowerCase()}.png`;

// A few pleasant, distinct tints; picked deterministically from the symbol.
const TINTS = ["#f0b90b", "#3498db", "#9b59b6", "#2ecc71", "#e67e22", "#1abc9c", "#e74c3c", "#5865f2"];

function tintFor(symbol: string): string {
  let h = 0;
  for (const ch of symbol) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TINTS[h % TINTS.length];
}

export function CoinIcon({ symbol, size = 22 }: { symbol: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const sym = (symbol || "?").toUpperCase();

  if (failed || !symbol) {
    return (
      <span
        className="coin-badge"
        style={{ width: size, height: size, fontSize: size * 0.38, background: tintFor(sym) }}
        aria-hidden
      >
        {sym.slice(0, 3)}
      </span>
    );
  }

  return (
    <img
      className="coin-img"
      src={CDN(sym)}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  );
}
