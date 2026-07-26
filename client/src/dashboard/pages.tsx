import { useEffect, useState } from "react";
import { api, type AuthUser, type Balance } from "../lib/api";
import { useTickers } from "../lib/useLive";
import { navigate } from "../router";

// Assets valued at ~1 USDT without needing a live feed.
const STABLE = new Set(["USDT", "USDC"]);

/** Live portfolio value + 24h PnL in USDT, priced from the live Binance feed. */
function usePortfolio(balances: Balance[] | null) {
  // Value every non-stable holding via its USDT pair.
  const symbols = (balances ?? [])
    .filter((b) => !STABLE.has(b.asset) && Number(b.total) > 0)
    .map((b) => `${b.asset}USDT`);
  const tickers = useTickers(symbols);

  let value = 0;
  let pnl24h = 0;
  for (const b of balances ?? []) {
    const total = Number(b.total);
    if (total <= 0) continue;
    if (STABLE.has(b.asset)) {
      value += total;
      continue;
    }
    const t = tickers[`${b.asset}USDT`];
    if (!t) continue;
    const worth = total * t.price;
    value += worth;
    // Today's PnL: how much this holding's value moved over 24h, from its live change%.
    pnl24h += worth - worth / (1 + t.changePercent / 100);
  }
  return { value, pnl24h, priced: symbols.every((s) => tickers[s]) };
}

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
  const { value, pnl24h } = usePortfolio(balances);
  const pnlUp = pnl24h >= 0;

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

      {/* balance — real, from the ledger, valued live from the Binance feed. */}
      <div className="balance-card">
        <div>
          <div className="balance-label">Est. Total Value ⓘ</div>
          <div className="balance-value">
            {balances === null ? "…" : value.toFixed(2)}
            <span className="unit">USDT</span>
          </div>
          <div className="balance-sub">
            {funded ? (
              <>
                Today's PnL{" "}
                <span style={{ color: pnlUp ? "#0ecb81" : "#f6465d" }}>
                  {pnlUp ? "+" : ""}{pnl24h.toFixed(2)} USDT
                </span>{" "}
                · live
              </>
            ) : (
              "No funds yet — an admin can credit test funds"
            )}
          </div>
        </div>
        <div className="balance-actions">
          <button className="btn-gold" onClick={() => navigate("/dashboard/trade")}>
            Trade
          </button>
          <button className="btn-outline-d" onClick={() => navigate("/dashboard/assets")}>
            Assets
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
