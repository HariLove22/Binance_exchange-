// Static content for the landing page. No live data yet — the ticker prices are
// seeded here and animated client-side to feel alive until the real market feed exists.

export interface Market {
  symbol: string; // e.g. "BTC/USDT"
  name: string; // e.g. "Bitcoin"
  price: number; // seed price
  change: number; // 24h % change, seed value
  icon: string; // short glyph / ticker letters
  color: string; // brand color for the coin chip
}

export const MARKETS: Market[] = [
  { symbol: "BTC/USDT", name: "Bitcoin", price: 67432.18, change: 2.41, icon: "₿", color: "#F7931A" },
  { symbol: "ETH/USDT", name: "Ethereum", price: 3521.04, change: 1.87, icon: "Ξ", color: "#627EEA" },
  { symbol: "BNB/USDT", name: "BNB", price: 604.55, change: -0.62, icon: "B", color: "#F0B90B" },
  { symbol: "SOL/USDT", name: "Solana", price: 172.9, change: 5.13, icon: "S", color: "#14F195" },
  { symbol: "XRP/USDT", name: "XRP", price: 0.6231, change: -1.24, icon: "X", color: "#23292F" },
  { symbol: "ADA/USDT", name: "Cardano", price: 0.4518, change: 0.94, icon: "A", color: "#0033AD" },
];

export interface Feature {
  title: string;
  body: string;
  icon: "shield" | "bolt" | "coins" | "chart" | "lock" | "globe";
}

export const FEATURES: Feature[] = [
  {
    icon: "bolt",
    title: "Matching engine built for speed",
    body: "A deterministic, integer-math order engine with price-time priority. Tens of thousands of orders a second, with a journal you can replay bit-for-bit.",
  },
  {
    icon: "shield",
    title: "Funds you can account for",
    body: "Every balance moves through a double-entry ledger that must balance to zero. Append-only, idempotent, audited — never a floating-point rupee out of place.",
  },
  {
    icon: "coins",
    title: "Low, transparent fees",
    body: "Maker and taker fees quoted up front. No hidden spread games, no surprise conversion cuts. What you see on the order form is what settles.",
  },
  {
    icon: "chart",
    title: "Pro trading, clean UI",
    body: "Live order book, depth chart, klines and open-orders — the tools serious traders expect, without the clutter that scares off everyone else.",
  },
  {
    icon: "lock",
    title: "Security first, always",
    body: "Institutional custody, withdrawal whitelists with time-locks, and a 24-hour freeze on any credential change. Your keys, guarded like they're ours.",
  },
  {
    icon: "globe",
    title: "Built for India",
    body: "INR on-ramp via UPI/IMPS P2P escrow, 1% TDS handled as a real ledger leg, and per-user FIFO cost basis so you can actually file your taxes.",
  },
];

export interface Stat {
  value: string;
  label: string;
}

export const STATS: Stat[] = [
  { value: "0.00", label: "Maker fee %" },
  { value: "24/7", label: "Markets open" },
  { value: "<10ms", label: "Engine match time" },
  { value: "100%", label: "Ledger reconciled" },
];

export const STEPS = [
  { n: "01", title: "Create your account", body: "Sign up in minutes with email. Complete KYC once and you're verified for life." },
  { n: "02", title: "Fund your wallet", body: "Add INR through UPI or bank transfer via secure P2P escrow, or deposit crypto." },
  { n: "03", title: "Start trading", body: "Buy, sell and set limit orders on a fast, transparent spot market. Keep every rupee accounted for." },
];
