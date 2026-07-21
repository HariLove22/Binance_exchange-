import type { ReactNode } from "react";
import { navigate } from "../../router";
import "../auth.css";

const HIGHLIGHTS = [
  "Integer-exact ledger — every rupee reconciled",
  "Deterministic matching engine, replayable journal",
  "INR on-ramp via secure UPI / IMPS P2P escrow",
];

// Split layout shared by Login & Signup: a branded marketing panel on the left,
// the form on the right. Collapses to a single column on small screens.
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <div className="auth-grid">
        <aside className="auth-brand">
          <div className="auth-brand-glow" aria-hidden />
          <a
            className="auth-logo"
            href="#/"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
          >
            <span className="brand-mark" aria-hidden>◈</span>
            <span>Novex</span>
          </a>

          <div className="auth-brand-body">
            <h2>Trade crypto with a ledger you can trust.</h2>
            <p>Join thousands trading on a fast, transparent spot exchange built for India.</p>
            <ul className="auth-highlights">
              {HIGHLIGHTS.map((h) => (
                <li key={h}>
                  <span className="tick" aria-hidden>✓</span>
                  {h}
                </li>
              ))}
            </ul>
          </div>

          <div className="auth-brand-foot">
            <div className="mini-book" aria-hidden>
              <span className="mb-row down"><i style={{ width: "60%" }} />67,438.20</span>
              <span className="mb-row down"><i style={{ width: "40%" }} />67,436.10</span>
              <span className="mb-mid">67,432.18 ▲</span>
              <span className="mb-row up"><i style={{ width: "52%" }} />67,428.40</span>
              <span className="mb-row up"><i style={{ width: "75%" }} />67,424.90</span>
            </div>
          </div>
        </aside>

        <main className="auth-panel">{children}</main>
      </div>
    </div>
  );
}
