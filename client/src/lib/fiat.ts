// Static fiat currency reference — deliberately NOT fetched from the API.
//
// Fiat currencies (ISO 4217) change so rarely that a live call is pure overhead: a network
// round-trip, a loading state, and a failure mode, all for data that is effectively constant.
// So this list ships with the bundle. The `flag` is stored explicitly rather than derived from
// the code, because the derivation (first two letters -> country) is wrong for supranational and
// shared currencies (EUR, XOF, XAF, XCD), and a wrong flag is worse than none.
//
// `perUsd` is an APPROXIMATE, static rate: how many units of the currency equal 1 USD. It exists
// so a price typed in, say, INR can be converted to the market's quote (USDT ~ USD) before an
// order is placed — the exchange trades in USDT, not fiat. It is intentionally coarse and matches
// the app's existing mock-rate approach (the on-ramp uses hardcoded rates too); it is not a live
// FX feed and should not be used where real accuracy matters.

export interface FiatCurrency {
  code: string; // ISO 4217 alphabetic code, e.g. "USD"
  name: string; // human-readable name, e.g. "US Dollar"
  flag: string; // emoji flag for the issuing country/union
  perUsd: number; // approximate units per 1 USD (USD itself = 1)
}

export const FIAT_CURRENCIES: FiatCurrency[] = [
  { code: "USD", name: "US Dollar", flag: "🇺🇸", perUsd: 1 },
  { code: "EUR", name: "Euro", flag: "🇪🇺", perUsd: 0.92 },
  { code: "GBP", name: "British Pound", flag: "🇬🇧", perUsd: 0.79 },
  { code: "INR", name: "Indian Rupee", flag: "🇮🇳", perUsd: 83.2 },
  { code: "AED", name: "UAE Dirham", flag: "🇦🇪", perUsd: 3.67 },
  { code: "SGD", name: "Singapore Dollar", flag: "🇸🇬", perUsd: 1.35 },
  { code: "JPY", name: "Japanese Yen", flag: "🇯🇵", perUsd: 157 },
  { code: "CNY", name: "Chinese Yuan", flag: "🇨🇳", perUsd: 7.25 },
  { code: "HKD", name: "Hong Kong Dollar", flag: "🇭🇰", perUsd: 7.8 },
  { code: "AUD", name: "Australian Dollar", flag: "🇦🇺", perUsd: 1.52 },
  { code: "CAD", name: "Canadian Dollar", flag: "🇨🇦", perUsd: 1.37 },
  { code: "CHF", name: "Swiss Franc", flag: "🇨🇭", perUsd: 0.88 },
  { code: "NZD", name: "New Zealand Dollar", flag: "🇳🇿", perUsd: 1.66 },
  { code: "SEK", name: "Swedish Krona", flag: "🇸🇪", perUsd: 10.9 },
  { code: "NOK", name: "Norwegian Krone", flag: "🇳🇴", perUsd: 10.9 },
  { code: "DKK", name: "Danish Krone", flag: "🇩🇰", perUsd: 6.9 },
  { code: "KRW", name: "South Korean Won", flag: "🇰🇷", perUsd: 1380 },
  { code: "TWD", name: "New Taiwan Dollar", flag: "🇹🇼", perUsd: 32.3 },
  { code: "THB", name: "Thai Baht", flag: "🇹🇭", perUsd: 36.5 },
  { code: "IDR", name: "Indonesian Rupiah", flag: "🇮🇩", perUsd: 16200 },
  { code: "MYR", name: "Malaysian Ringgit", flag: "🇲🇾", perUsd: 4.7 },
  { code: "PHP", name: "Philippine Peso", flag: "🇵🇭", perUsd: 58.5 },
  { code: "VND", name: "Vietnamese Dong", flag: "🇻🇳", perUsd: 25400 },
  { code: "PKR", name: "Pakistani Rupee", flag: "🇵🇰", perUsd: 278 },
  { code: "BDT", name: "Bangladeshi Taka", flag: "🇧🇩", perUsd: 118 },
  { code: "LKR", name: "Sri Lankan Rupee", flag: "🇱🇰", perUsd: 300 },
  { code: "NPR", name: "Nepalese Rupee", flag: "🇳🇵", perUsd: 133 },
  { code: "SAR", name: "Saudi Riyal", flag: "🇸🇦", perUsd: 3.75 },
  { code: "QAR", name: "Qatari Riyal", flag: "🇶🇦", perUsd: 3.64 },
  { code: "KWD", name: "Kuwaiti Dinar", flag: "🇰🇼", perUsd: 0.31 },
  { code: "BHD", name: "Bahraini Dinar", flag: "🇧🇭", perUsd: 0.376 },
  { code: "OMR", name: "Omani Rial", flag: "🇴🇲", perUsd: 0.385 },
  { code: "JOD", name: "Jordanian Dinar", flag: "🇯🇴", perUsd: 0.709 },
  { code: "ILS", name: "Israeli New Shekel", flag: "🇮🇱", perUsd: 3.7 },
  { code: "TRY", name: "Turkish Lira", flag: "🇹🇷", perUsd: 34.5 },
  { code: "EGP", name: "Egyptian Pound", flag: "🇪🇬", perUsd: 49 },
  { code: "ZAR", name: "South African Rand", flag: "🇿🇦", perUsd: 18.4 },
  { code: "NGN", name: "Nigerian Naira", flag: "🇳🇬", perUsd: 1550 },
  { code: "KES", name: "Kenyan Shilling", flag: "🇰🇪", perUsd: 129 },
  { code: "GHS", name: "Ghanaian Cedi", flag: "🇬🇭", perUsd: 15.3 },
  { code: "MAD", name: "Moroccan Dirham", flag: "🇲🇦", perUsd: 9.9 },
  { code: "DZD", name: "Algerian Dinar", flag: "🇩🇿", perUsd: 134 },
  { code: "TND", name: "Tunisian Dinar", flag: "🇹🇳", perUsd: 3.13 },
  { code: "AOA", name: "Angolan Kwanza", flag: "🇦🇴", perUsd: 910 },
  { code: "BRL", name: "Brazilian Real", flag: "🇧🇷", perUsd: 5.6 },
  { code: "MXN", name: "Mexican Peso", flag: "🇲🇽", perUsd: 18.5 },
  { code: "ARS", name: "Argentine Peso", flag: "🇦🇷", perUsd: 970 },
  { code: "CLP", name: "Chilean Peso", flag: "🇨🇱", perUsd: 950 },
  { code: "COP", name: "Colombian Peso", flag: "🇨🇴", perUsd: 4100 },
  { code: "PEN", name: "Peruvian Sol", flag: "🇵🇪", perUsd: 3.75 },
  { code: "RUB", name: "Russian Ruble", flag: "🇷🇺", perUsd: 92 },
  { code: "UAH", name: "Ukrainian Hryvnia", flag: "🇺🇦", perUsd: 41 },
  { code: "PLN", name: "Polish Zloty", flag: "🇵🇱", perUsd: 3.95 },
  { code: "CZK", name: "Czech Koruna", flag: "🇨🇿", perUsd: 23.2 },
  { code: "HUF", name: "Hungarian Forint", flag: "🇭🇺", perUsd: 360 },
  { code: "RON", name: "Romanian Leu", flag: "🇷🇴", perUsd: 4.6 },
  { code: "KZT", name: "Kazakhstani Tenge", flag: "🇰🇿", perUsd: 480 },
  { code: "GEL", name: "Georgian Lari", flag: "🇬🇪", perUsd: 2.7 },
  { code: "AZN", name: "Azerbaijani Manat", flag: "🇦🇿", perUsd: 1.7 },
  { code: "AMD", name: "Armenian Dram", flag: "🇦🇲", perUsd: 388 },
];

/** Case-insensitive lookup by code. */
export function findFiat(code: string): FiatCurrency | undefined {
  const upper = code.toUpperCase();
  return FIAT_CURRENCIES.find((c) => c.code === upper);
}

/**
 * Filter by code or name, case-insensitively. Empty query returns the full list.
 * Matching the name (not just the code) is what lets someone type "rupee" or "dram".
 */
export function searchFiat(query: string): FiatCurrency[] {
  const q = query.trim().toLowerCase();
  if (!q) return FIAT_CURRENCIES;
  return FIAT_CURRENCIES.filter(
    (c) => c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q),
  );
}

/** Approximate units-per-USD for a code, or null if unknown. USDT is treated as ~1 USD. */
export function ratePerUsd(code: string): number | null {
  const upper = code.toUpperCase();
  if (upper === "USDT" || upper === "USDC") return 1;
  return findFiat(upper)?.perUsd ?? null;
}
