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
              navigate("landing");
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

// Small "unavailable" notice shown after submit — the backend has no auth yet
// (per docs: "no auth yet"). Honest placeholder instead of a fake success.
export function AuthNotice({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="auth-notice" role="status">
      Looks good — but the auth backend isn't wired up yet. This form is ready for the API once
      the accounts endpoint lands.
    </div>
  );
}
