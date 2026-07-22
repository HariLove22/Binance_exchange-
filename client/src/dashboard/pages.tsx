import { useEffect, useState } from "react";
import { api, type AuthUser, type Balance } from "../lib/api";
import { navigate } from "../router";

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
  const [balances, setBalances] = useState<Balance[] | null>(null);

  useEffect(() => {
    // Best-effort: the overview still renders if this fails; the Assets page surfaces errors.
    api.balances().then(setBalances).catch(() => setBalances([]));
  }, []);

  const assetCount = balances?.filter((b) => b.total !== "0" && Number(b.available) + Number(b.locked) > 0).length ?? 0;
  const funded = assetCount > 0;

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

        <div className="step-card active">
          <span className="step-num">2</span>
          <h3>Complete a Deposit to Start Your Trading Journey</h3>
          <p>Add funds to your account to begin trading crypto on Novex.</p>
          <div className="step-cta">
            <button className="btn-gold">Deposit</button>
          </div>
        </div>

        <div className="step-card">
          <span className="step-num">3</span>
          <h3>Trade</h3>
          <p>Buy and sell crypto once your deposit lands.</p>
          <div className="step-cta">
            <span className="step-pending">◷ Pending</span>
          </div>
        </div>
      </div>

      {/* balance — real, from the ledger. No fiat total: we don't price assets yet, and a
          faked "≈ ₹0.00" would misrepresent what exists. */}
      <div className="balance-card">
        <div>
          <div className="balance-label">Spot assets held</div>
          <div className="balance-value">
            {balances === null ? "…" : assetCount}
            <span className="unit">{assetCount === 1 ? "asset" : "assets"}</span>
          </div>
          <div className="balance-sub">
            {funded
              ? "View balances on the Assets → Spot page"
              : "No funds yet — credit test funds via python -m app.dev_credit"}
          </div>
        </div>
        <div className="balance-actions">
          <button className="btn-gold" onClick={() => navigate("/dashboard/assets")}>
            View Assets
          </button>
          <button className="btn-outline-d" disabled title="Needs a custody provider">
            Deposit
          </button>
          <button className="btn-outline-d" disabled title="Needs a custody provider">
            Withdraw
          </button>
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
