import { SystemStatus } from "./SystemStatus";

const COLS = [
  { title: "Products", links: ["Spot trading", "P2P (INR)", "Markets", "Fees"] },
  { title: "Company", links: ["About", "Careers", "Blog", "Press"] },
  { title: "Support", links: ["Help center", "Contact", "API docs", "Status"] },
  { title: "Legal", links: ["Terms", "Privacy", "AML policy", "Risk disclosure"] },
];

const SOCIALS = ["x-icon", "github-icon", "discord-icon", "bluesky-icon"];

export function Footer() {
  return (
    <footer className="footer" id="footer">
      <div className="footer-inner">
        <div className="footer-brand">
          <a className="brand" href="#top">
            <span className="brand-mark" aria-hidden>◈</span>
            <span className="brand-name">Novex</span>
          </a>
          <p>A spot crypto exchange built on exact accounting. Made for India.</p>
          <SystemStatus />
          <div className="socials">
            {SOCIALS.map((id) => (
              <a key={id} href="#footer" className="social" aria-label={id.replace("-icon", "")}>
                <svg width="18" height="18" aria-hidden>
                  <use href={`/icons.svg#${id}`} />
                </svg>
              </a>
            ))}
          </div>
        </div>

        <div className="footer-cols">
          {COLS.map((c) => (
            <div className="footer-col" key={c.title}>
              <h4>{c.title}</h4>
              <ul>
                {c.links.map((l) => (
                  <li key={l}>
                    <a href="#footer">{l}</a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div className="footer-base">
        <span>© 2026 Novex Exchange. Trading crypto carries risk.</span>
        <span className="footer-disc">Not investment advice. FIU-IND registration in progress.</span>
      </div>
    </footer>
  );
}
