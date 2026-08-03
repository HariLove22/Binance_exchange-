import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

/**
 * i18next setup. Every src/locales/<code>/translation.json is auto-loaded — adding a language is
 * just dropping a file, no code change here. Any switcher language without a file falls back to en.
 *
 * The detector reads `novex_language` from localStorage — the SAME key lib/locale writes — so the
 * switcher's setLanguage() → i18n.changeLanguage() keeps the two in sync.
 */
const modules = import.meta.glob("./locales/*/translation.json", { eager: true }) as Record<
  string,
  { default: Record<string, unknown> }
>;

const resources: Record<string, { translation: Record<string, unknown> }> = {};
for (const path in modules) {
  const code = path.split("/")[2]; // ./locales/<code>/translation.json
  resources[code] = { translation: modules[path].default };
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "en",
    supportedLngs: Object.keys(resources),
    nonExplicitSupportedLngs: true, // "hi-IN" resolves to "hi"
    interpolation: { escapeValue: false }, // React already escapes
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "novex_language",
      caches: ["localStorage"],
    },
  });

export default i18n;
