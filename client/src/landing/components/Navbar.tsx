import { useEffect, useState } from "react";
import { navigate } from "../../router";
import { useAuth } from "../../auth/AuthContext";

const LINKS = [
  { label: "Markets", href: "#markets" },
  { label: "Features", href: "#features" },
  { label: "How it works", href: "#how" },
  { label: "Company", href: "#footer" },
];

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const { user, logout } = useAuth();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`nav ${scrolled ? "nav-scrolled" : ""}`}>
      <div className="nav-inner">
        <a className="brand" href="#top">
          <span className="brand-mark" aria-hidden>◈</span>
          <span className="brand-name">Novex</span>
        </a>

        <nav className="nav-links">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
        </nav>

        <div className="nav-actions">
          {user ? (
            <>
              <button className="btn btn-ghost" onClick={logout}>
                Log out
              </button>
              <button className="btn btn-primary" onClick={() => navigate("/dashboard")}>
                Dashboard
              </button>
            </>
          ) : (
            <>
              <button className="btn btn-ghost" onClick={() => navigate("/login")}>
                Log in
              </button>
              <button className="btn btn-primary" onClick={() => navigate("/signup")}>
                Sign up
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
