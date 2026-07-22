import type { AuthUser } from "../lib/api";
import { ISpark } from "./icons";
import { navigate } from "../router";
import { isNonZero, useBalances } from "./useBalances";

function initial(user: AuthUser): string {
  return (user.full_name?.trim()?.[0] ?? user.email[0] ?? "U").toUpperCase();
}

// A stable pseudo-UID derived from the user id, formatted like an exchange UID.
function uid(user: AuthUser): string {
  return String(1_000_000_000 + user.id);
}

function handle(user: AuthUser): string {
  return `User-${user.id.toString(16).padStart(5, "0")}`;
}

export function Overview({ user }: { user: AuthUser }) {
  const { balances, loading } = useBalances();
  const btc = balances.find((b) => b.asset === "BTC");
  const funded = balances.some((b) => isNonZero(b.total));

  return (
    <div>
      {/* profile header */}
      <div className="profile">
        <div className="profile-avatar">{initial(user)}</div>
        <div className="profile-id">
          <div className="p-name">
            {user.full_name || handle(user)}
            <span className="social-chip">Link Social Account ›</span>
          </div>
          <div style={{ color: "var(--text-faint)", fontSize: ".85rem", marginTop: ".25rem" }}>
            {handle(user)} · {user.email}
          </div>
        </div>

        <div className="profile-stats">
          <div>
            <div className="ps-label">UID</div>
            <div className="ps-val">{uid(user)}</div>
          </div>
          <div>
            <div className="ps-label">VIP Level</div>
            <div className="ps-val">Regular User ›</div>
          </div>
          <div>
            <div className="ps-label">Following</div>
            <div className="ps-val">0 ›</div>
          </div>
          <div>
            <div className="ps-label">Followers</div>
            <div className="ps-val">0 ›</div>
          </div>
        </div>
      </div>

      {/* get started */}
      <h2 className="section-title">Get Started</h2>
      <div className="steps">
        <div className="step-card">
          <span className="step-num">1</span>
          <h3>Verification {user.is_verified ? "Complete" : "Under Review"}</h3>
          <p>
            {user.is_verified
              ? "Your email is verified. Identity (KYC) verification will unlock higher limits."
              : "Your details are being reviewed. This usually takes a few minutes."}
          </p>
          <div className="step-cta">
            <button className="btn-outline-d">View Details</button>
          </div>
        </div>

        <div className={`step-card ${funded ? "" : "active"}`}>
          <span className="step-num">2</span>
          <h3>{funded ? "Funds Added" : "Complete a Deposit to Start Your Trading Journey"}</h3>
          <p>
            {funded
              ? "Your account is funded. You're ready to place your first order."
              : "Add funds to your account to begin trading crypto on Novex."}
          </p>
          <div className="step-cta">
            <button className="btn-gold" onClick={() => navigate("/dashboard/assets")}>
              {funded ? "View assets" : "Deposit"}
            </button>
          </div>
        </div>

        <div className={`step-card ${funded ? "active" : ""}`}>
          <span className="step-num">3</span>
          <h3>Trade</h3>
          <p>Buy and sell crypto on the order book.</p>
          <div className="step-cta">
            {funded ? (
              <button className="btn-outline-d">Trade (coming next)</button>
            ) : (
              <span className="step-pending">◷ Pending</span>
            )}
          </div>
        </div>
      </div>

      {/* balances — real numbers from the ledger */}
      <div className="balance-card">
        <div>
          <div className="balance-label">BTC Balance</div>
          <div className="balance-value">
            {loading ? "…" : (btc?.total ?? "0.00000000")}
            <span className="unit">BTC</span>
          </div>
          <div className="balance-sub">
            {/* An "Est. Total Value" across assets needs a price feed — that arrives with trading. */}
            {loading
              ? " "
              : balances.filter((b) => isNonZero(b.total) && b.asset !== "BTC").length > 0
                ? balances
                    .filter((b) => isNonZero(b.total) && b.asset !== "BTC")
                    .map((b) => `${b.total} ${b.asset}`)
                    .join(" · ")
                : "No other holdings yet"}
          </div>
        </div>
        <div className="balance-actions">
          <button className="chip-ai">
            <ISpark className="ic" style={{ width: 16, height: 16 }} /> How's the market today?
          </button>
          <button className="btn-gold" onClick={() => navigate("/dashboard/assets")}>Deposit</button>
          <button className="btn-outline-d">Withdraw</button>
          <button className="btn-outline-d">Cash In</button>
        </div>
      </div>
    </div>
  );
}

export function Placeholder({ title, icon }: { title: string; icon: string }) {
  return (
    <div className="placeholder">
      <div>
        <div className="ph-icon">{icon}</div>
        <h2>{title}</h2>
        <p>This section is coming soon. The route is live and protected — content lands next.</p>
      </div>
    </div>
  );
}
