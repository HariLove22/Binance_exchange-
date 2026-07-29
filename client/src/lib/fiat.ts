// Static fiat currency reference — deliberately NOT fetched from the API.
//
// Fiat currencies (ISO 4217) change so rarely that a live call is pure overhead: a network
// round-trip, a loading state, and a failure mode, all for data that is effectively constant.
// So this list ships with the bundle. The `flag` is stored explicitly rather than derived from
// the code, because the derivation (first two letters -> country) is wrong for supranational and
// shared currencies (EUR, XOF, XAF, XCD), and a wrong flag is worse than none.
//
// Note: this is the *display* list for the picker. Whether a given currency can actually be
// bought with depends on the backend having a rate for it (see onramp FIAT_RATES) — the buy
// form degrades gracefully (no quote -> button disabled) when it doesn't.

export interface FiatCurrency {
  code: string; // ISO 4217 alphabetic code, e.g. "USD"
  name: string; // human-readable name, e.g. "US Dollar"
  flag: string; // emoji flag for the issuing country/union
}

export const FIAT_CURRENCIES: FiatCurrency[] = [
  { code: "USD", name: "US Dollar", flag: "🇺🇸" },
  { code: "EUR", name: "Euro", flag: "🇪🇺" },
  { code: "GBP", name: "British Pound", flag: "🇬🇧" },
  { code: "INR", name: "Indian Rupee", flag: "🇮🇳" },
  { code: "AED", name: "UAE Dirham", flag: "🇦🇪" },
  { code: "SGD", name: "Singapore Dollar", flag: "🇸🇬" },
  { code: "JPY", name: "Japanese Yen", flag: "🇯🇵" },
  { code: "CNY", name: "Chinese Yuan", flag: "🇨🇳" },
  { code: "HKD", name: "Hong Kong Dollar", flag: "🇭🇰" },
  { code: "AUD", name: "Australian Dollar", flag: "🇦🇺" },
  { code: "CAD", name: "Canadian Dollar", flag: "🇨🇦" },
  { code: "CHF", name: "Swiss Franc", flag: "🇨🇭" },
  { code: "NZD", name: "New Zealand Dollar", flag: "🇳🇿" },
  { code: "SEK", name: "Swedish Krona", flag: "🇸🇪" },
  { code: "NOK", name: "Norwegian Krone", flag: "🇳🇴" },
  { code: "DKK", name: "Danish Krone", flag: "🇩🇰" },
  { code: "KRW", name: "South Korean Won", flag: "🇰🇷" },
  { code: "TWD", name: "New Taiwan Dollar", flag: "🇹🇼" },
  { code: "THB", name: "Thai Baht", flag: "🇹🇭" },
  { code: "IDR", name: "Indonesian Rupiah", flag: "🇮🇩" },
  { code: "MYR", name: "Malaysian Ringgit", flag: "🇲🇾" },
  { code: "PHP", name: "Philippine Peso", flag: "🇵🇭" },
  { code: "VND", name: "Vietnamese Dong", flag: "🇻🇳" },
  { code: "PKR", name: "Pakistani Rupee", flag: "🇵🇰" },
  { code: "BDT", name: "Bangladeshi Taka", flag: "🇧🇩" },
  { code: "LKR", name: "Sri Lankan Rupee", flag: "🇱🇰" },
  { code: "NPR", name: "Nepalese Rupee", flag: "🇳🇵" },
  { code: "SAR", name: "Saudi Riyal", flag: "🇸🇦" },
  { code: "QAR", name: "Qatari Riyal", flag: "🇶🇦" },
  { code: "KWD", name: "Kuwaiti Dinar", flag: "🇰🇼" },
  { code: "BHD", name: "Bahraini Dinar", flag: "🇧🇭" },
  { code: "OMR", name: "Omani Rial", flag: "🇴🇲" },
  { code: "JOD", name: "Jordanian Dinar", flag: "🇯🇴" },
  { code: "ILS", name: "Israeli New Shekel", flag: "🇮🇱" },
  { code: "TRY", name: "Turkish Lira", flag: "🇹🇷" },
  { code: "EGP", name: "Egyptian Pound", flag: "🇪🇬" },
  { code: "ZAR", name: "South African Rand", flag: "🇿🇦" },
  { code: "NGN", name: "Nigerian Naira", flag: "🇳🇬" },
  { code: "KES", name: "Kenyan Shilling", flag: "🇰🇪" },
  { code: "GHS", name: "Ghanaian Cedi", flag: "🇬🇭" },
  { code: "MAD", name: "Moroccan Dirham", flag: "🇲🇦" },
  { code: "DZD", name: "Algerian Dinar", flag: "🇩🇿" },
  { code: "TND", name: "Tunisian Dinar", flag: "🇹🇳" },
  { code: "AOA", name: "Angolan Kwanza", flag: "🇦🇴" },
  { code: "BRL", name: "Brazilian Real", flag: "🇧🇷" },
  { code: "MXN", name: "Mexican Peso", flag: "🇲🇽" },
  { code: "ARS", name: "Argentine Peso", flag: "🇦🇷" },
  { code: "CLP", name: "Chilean Peso", flag: "🇨🇱" },
  { code: "COP", name: "Colombian Peso", flag: "🇨🇴" },
  { code: "PEN", name: "Peruvian Sol", flag: "🇵🇪" },
  { code: "RUB", name: "Russian Ruble", flag: "🇷🇺" },
  { code: "UAH", name: "Ukrainian Hryvnia", flag: "🇺🇦" },
  { code: "PLN", name: "Polish Zloty", flag: "🇵🇱" },
  { code: "CZK", name: "Czech Koruna", flag: "🇨🇿" },
  { code: "HUF", name: "Hungarian Forint", flag: "🇭🇺" },
  { code: "RON", name: "Romanian Leu", flag: "🇷🇴" },
  { code: "KZT", name: "Kazakhstani Tenge", flag: "🇰🇿" },
  { code: "GEL", name: "Georgian Lari", flag: "🇬🇪" },
  { code: "AZN", name: "Azerbaijani Manat", flag: "🇦🇿" },
  { code: "AMD", name: "Armenian Dram", flag: "🇦🇲" },
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
