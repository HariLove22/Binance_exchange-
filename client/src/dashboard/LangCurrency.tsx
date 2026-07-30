import { useEffect, useRef, useState } from "react";
import { CURRENCIES, LANGUAGES, useLocale } from "../lib/locale";
import "./langcurrency.css";

/** Globe-icon dropdown: pick display language and currency, both searchable, like Binance's. */
export function LangCurrency() {
  const { currency, setCurrency, language, setLanguage } = useLocale();
  const [open, setOpen] = useState(false);
  const [langQ, setLangQ] = useState("");
  const [curQ, setCurQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const langs = LANGUAGES.filter((l) => l.label.toLowerCase().includes(langQ.toLowerCase()) || l.code.includes(langQ.toLowerCase()));
  const curs = CURRENCIES.filter((c) => c.code.toLowerCase().includes(curQ.toLowerCase()));

  return (
    <div className="lc-wrap" ref={ref}>
      <button className="icon-btn" aria-label="Language and currency" onClick={() => setOpen((o) => !o)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" /><path d="M2 12h20" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
      </button>
      {open && (
        <div className="lc-panel">
          <div className="lc-col">
            <div className="lc-title">Language</div>
            <input className="lc-search" value={langQ} onChange={(e) => setLangQ(e.target.value)} placeholder="Search" />
            <div className="lc-list">
              {langs.map((l) => (
                <button key={l.code} className={`lc-item ${language === l.code ? "on" : ""}`}
                        onClick={() => { setLanguage(l.code); }}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          <div className="lc-col">
            <div className="lc-title">Currency</div>
            <input className="lc-search" value={curQ} onChange={(e) => setCurQ(e.target.value)} placeholder="Search" />
            <div className="lc-list">
              {curs.map((c) => (
                <button key={c.code} className={`lc-item ${currency.code === c.code ? "on" : ""}`}
                        onClick={() => { setCurrency(c.code); setOpen(false); }}>
                  {c.code}-{c.symbol}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
