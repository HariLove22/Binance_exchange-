// Fixed-decimal string <-> integer units.
//
// The API sends money as strings on purpose. The moment you parseFloat one you're back in
// IEEE 754 and 0.1 + 0.2 != 0.3. So any arithmetic here (cumulative depth totals) goes
// through BigInt and comes back out as a string. Numbers are only ever used for pixel
// widths, which are not money.

export function scaleOf(s: string): number {
  const i = s.indexOf(".");
  return i < 0 ? 0 : s.length - i - 1;
}

export function toUnits(s: string, scale: number): bigint {
  const neg = s.startsWith("-");
  const body = neg ? s.slice(1) : s;
  const [int, frac = ""] = body.split(".");
  const padded = (frac + "0".repeat(scale)).slice(0, scale);
  const v = BigInt((int || "0") + padded);
  return neg ? -v : v;
}

export function fromUnits(units: bigint, scale: number): string {
  const neg = units < 0n;
  const abs = (neg ? -units : units).toString().padStart(scale + 1, "0");
  const out = scale === 0 ? abs : `${abs.slice(0, -scale)}.${abs.slice(-scale)}`;
  return neg ? `-${out}` : out;
}

export function withThousands(s: string): string {
  const [int, frac] = s.split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return frac ? `${grouped}.${frac}` : grouped;
}

/**
 * price x quantity, both fixed-decimal strings, result at the same scale.
 * Integer division truncates the tail — fine for the form's "Total" preview, which is an
 * estimate shown to the user. The authoritative number is always computed server-side.
 */
export function multiply(a: string, b: string, scale: number): string {
  const prod = (toUnits(a, scale) * toUnits(b, scale)) / 10n ** BigInt(scale);
  return fromUnits(prod, scale);
}

/**
 * Exact price x quantity, for "what did this fill actually cost".
 *
 * The result comes back at `scale * 2` because that is the product's true scale — two 8dp
 * numbers multiply to 16dp. `multiply` above truncates back to `scale`, which is fine for a
 * throwaway preview but wrong here: truncating each leg independently makes a column of fills
 * stop adding up to its own total, and a receipt whose numbers don't sum reads as a bug.
 * Display trims the tail with `trimZeros`, which only ever hides zeros.
 */
export function product(price: string, quantity: string, scale: number): string {
  return fromUnits(toUnits(price, scale) * toUnits(quantity, scale), scale * 2);
}

/** Exact Σ (price × quantity) across fills, at `scale * 2` — see `product`. */
export function sumProducts(
  legs: ReadonlyArray<{ price: string; quantity: string }>,
  scale: number,
): string {
  const total = legs.reduce(
    (acc, leg) => acc + toUnits(leg.price, scale) * toUnits(leg.quantity, scale),
    0n,
  );
  return fromUnits(total, scale * 2);
}

/** True when a decimal string parses and is greater than zero. */
export function isPositive(s: string): boolean {
  if (!/^\d*\.?\d*$/.test(s.trim()) || s.trim() === "" || s.trim() === ".") return false;
  return /[1-9]/.test(s);
}

/** Shorten to `places` decimals ONLY when the dropped digits are zeros — never hides a value. */
export function trimZeros(s: string, places: number): string {
  const i = s.indexOf(".");
  if (i < 0) return s;
  const frac = s.slice(i + 1);
  if (frac.length <= places) return s;
  const dropped = frac.slice(places);
  if (/[1-9]/.test(dropped)) return s; // real digits out there — keep full precision
  return places === 0 ? s.slice(0, i) : `${s.slice(0, i)}.${frac.slice(0, places)}`;
}
