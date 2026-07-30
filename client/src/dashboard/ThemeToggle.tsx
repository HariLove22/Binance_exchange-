import { useEffect, useState } from "react";

type Theme = "dark" | "light";
const KEY = "novex_theme";

export function applyStoredTheme() {
  const t = (localStorage.getItem(KEY) as Theme | null) ?? "dark";
  document.documentElement.setAttribute("data-theme", t);
}

/** Sun/moon toggle in the top bar. Flips a `data-theme` attribute the CSS keys off, persisted. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem(KEY) as Theme | null) ?? "dark");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const next = theme === "dark" ? "light" : "dark";
  return (
    <button className="icon-btn theme-toggle" aria-label={`Switch to ${next} mode`} title={`Switch to ${next} mode`}
            onClick={() => setTheme(next)}>
      {theme === "dark" ? (
        // moon
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      ) : (
        // sun
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
      )}
    </button>
  );
}
