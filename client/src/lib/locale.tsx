import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import i18n from "../i18n";

/**
 * Locale: the user's display currency and language, persisted across sessions.
 *
 * Currency is fully live — pick INR and every USD value re-renders as ₹ at the stored rate. Language
 * sets the document language and is the switch a translation layer keys off; wrapping each string in
 * `t()` (or plugging a translation service) is what makes the copy itself change — the selection and
 * plumbing live here so that work is additive.
 */

export type FiatCurrency = { code: string; symbol: string; perUsd: number };

// A broad set with rough USD rates (display only). Extend freely.
export const CURRENCIES: FiatCurrency[] = [
  { code: "USD", symbol: "$", perUsd: 1 },
  { code: "AED", symbol: "د.إ", perUsd: 3.67 },
  { code: "ARS", symbol: "ARS$", perUsd: 950 },
  { code: "AUD", symbol: "A$", perUsd: 1.51 },
  { code: "AZN", symbol: "₼", perUsd: 1.7 },
  { code: "BDT", symbol: "৳", perUsd: 118 },
  { code: "BGN", symbol: "лв", perUsd: 1.8 },
  { code: "BHD", symbol: ".د.ب", perUsd: 0.376 },
  { code: "BRL", symbol: "R$", perUsd: 5.5 },
  { code: "CAD", symbol: "C$", perUsd: 1.37 },
  { code: "CHF", symbol: "Fr", perUsd: 0.88 },
  { code: "CNY", symbol: "¥", perUsd: 7.25 },
  { code: "EUR", symbol: "€", perUsd: 0.92 },
  { code: "GBP", symbol: "£", perUsd: 0.79 },
  { code: "HKD", symbol: "HK$", perUsd: 7.8 },
  { code: "IDR", symbol: "Rp", perUsd: 16200 },
  { code: "INR", symbol: "₹", perUsd: 83.2 },
  { code: "JPY", symbol: "¥", perUsd: 157 },
  { code: "KRW", symbol: "₩", perUsd: 1380 },
  { code: "MYR", symbol: "RM", perUsd: 4.7 },
  { code: "NGN", symbol: "₦", perUsd: 1600 },
  { code: "PHP", symbol: "₱", perUsd: 58 },
  { code: "PKR", symbol: "₨", perUsd: 278 },
  { code: "RUB", symbol: "₽", perUsd: 90 },
  { code: "SAR", symbol: "﷼", perUsd: 3.75 },
  { code: "SGD", symbol: "S$", perUsd: 1.35 },
  { code: "THB", symbol: "฿", perUsd: 36 },
  { code: "TRY", symbol: "₺", perUsd: 33 },
  { code: "UAH", symbol: "₴", perUsd: 41 },
  { code: "VND", symbol: "₫", perUsd: 25400 },
  { code: "ZAR", symbol: "R", perUsd: 18.5 },
];

// Languages a user can pick. `t` currently returns the base copy; the selection persists and sets
// the document language so a translation layer (files or a service) can take over without UI changes.
export const LANGUAGES: { code: string; label: string }[] = [
  { code: "en", label: "English" },
  { code: "ar", label: "العربية" },
  { code: "az", label: "Azərbaycan" },
  { code: "de", label: "Deutsch" },
  { code: "es", label: "Español" },
  { code: "fr", label: "Français" },
  { code: "hi", label: "हिन्दी" },
  { code: "id", label: "Bahasa Indonesia" },
  { code: "ja", label: "日本語" },
  { code: "ko", label: "한국어" },
  { code: "pt", label: "Português" },
  { code: "ru", label: "Русский" },
  { code: "tr", label: "Türkçe" },
  { code: "uk", label: "Українська" },
  { code: "vi", label: "Tiếng Việt" },
  { code: "zh", label: "中文 (简体)" },
];

type LocaleState = {
  currency: FiatCurrency;
  setCurrency: (code: string) => void;
  language: string;
  setLanguage: (code: string) => void;
  /** Convert a USD amount to the display currency. */
  fromUsd: (usd: number) => number;
  /** Format a USD amount as the display currency (with symbol). */
  fmt: (usd: number, opts?: Intl.NumberFormatOptions) => string;
};

const Ctx = createContext<LocaleState | null>(null);
const CUR_KEY = "novex_currency";
const LANG_KEY = "novex_language";

function findCurrency(code: string): FiatCurrency {
  return CURRENCIES.find((c) => c.code === code) ?? CURRENCIES[0];
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [currency, setCur] = useState<FiatCurrency>(() => findCurrency(localStorage.getItem(CUR_KEY) ?? "USD"));
  const [language, setLang] = useState<string>(() => localStorage.getItem(LANG_KEY) ?? "en");

  useEffect(() => { document.documentElement.setAttribute("lang", language); }, [language]);

  const setCurrency = (code: string) => { const c = findCurrency(code); localStorage.setItem(CUR_KEY, c.code); setCur(c); };
  // Also drive i18next so every t() re-renders in the new language instantly.
  const setLanguage = (code: string) => { localStorage.setItem(LANG_KEY, code); setLang(code); void i18n.changeLanguage(code); };

  const fromUsd = (usd: number) => usd * currency.perUsd;
  const fmt = (usd: number, opts?: Intl.NumberFormatOptions) =>
    `${currency.symbol}${fromUsd(usd).toLocaleString(undefined, { maximumFractionDigits: 2, ...opts })}`;

  return <Ctx.Provider value={{ currency, setCurrency, language, setLanguage, fromUsd, fmt }}>{children}</Ctx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useLocale(): LocaleState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLocale must be used within <LocaleProvider>");
  return ctx;
}
