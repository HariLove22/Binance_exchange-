import { useEffect, useState } from "react";
import { api, type KycStatus } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { navigate } from "../router";
import "./account.css";

/**
 * The user's profile — a read view of who they are on the exchange: identity, UID, verification
 * status, and quick links to edit details, verify identity, or manage security.
 */
export function Profile() {
  const { user } = useAuth();
  const [kyc, setKyc] = useState<KycStatus | null>(null);
  useEffect(() => { api.kycMe().then(setKyc).catch(() => setKyc(null)); }, []);
  if (!user) return null;

  const since = new Date(user.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  const uid = String(1_000_000_000 + user.id);
  const verified = kyc?.status === "APPROVED";

  return (
    <div className="acct">
      <h1>Profile</h1>

      <section className="acct-card acct-profile">
        <div className="acct-avatar">{(user.full_name?.[0] ?? user.email[0]).toUpperCase()}</div>
        <div className="acct-id">
          <div className="acct-name">{user.full_name}</div>
          <div className="acct-email">{user.email}</div>
          <div className="acct-badges">
            <span className={`acct-badge ${user.role === "ADMIN" ? "admin" : ""}`}>{user.role}</span>
            <span className={`acct-badge ${verified ? "ok" : kyc?.status === "PENDING" ? "" : "muted"}`}>
              {verified ? "Verified" : kyc?.status === "PENDING" ? "KYC Pending" : "Unverified"}
            </span>
          </div>
        </div>
        <div className="acct-meta">
          <div><span>UID</span><b>{uid}</b></div>
          <div><span>Member since</span><b>{since}</b></div>
        </div>
      </section>

      <div className="acct-grid">
        <section className="acct-card">
          <h2>Details</h2>
          <div className="pf-row"><span>Full name</span><b>{user.full_name}</b></div>
          <div className="pf-row"><span>Email</span><b>{user.email}</b></div>
          <div className="pf-row"><span>User ID</span><b>#{user.id}</b></div>
          <div className="pf-row"><span>Role</span><b>{user.role}</b></div>
          <button className="acct-primary" style={{ marginTop: "0.8rem" }} onClick={() => navigate("/dashboard/settings")}>Edit profile</button>
        </section>

        <section className="acct-card">
          <h2>Verification</h2>
          <div className="pf-row"><span>Identity (KYC)</span>
            <b style={{ color: verified ? "#2bd97c" : kyc?.status === "PENDING" ? "#f0b90b" : undefined }}>
              {verified ? "Verified ✓" : kyc?.status === "PENDING" ? "Under review" : kyc?.status === "REJECTED" ? "Rejected" : "Not verified"}
            </b>
          </div>
          {kyc?.status === "REJECTED" && kyc.reject_reason && <p className="acct-row-sub" style={{ margin: "0.2rem 0" }}>{kyc.reject_reason}</p>}
          <p className="acct-row-sub">Verified accounts unlock trading and higher limits.</p>
          {!verified && (
            <button className="acct-primary" style={{ marginTop: "0.6rem" }} onClick={() => navigate("/dashboard/verification")}>
              {kyc?.status === "PENDING" ? "View status" : "Verify identity"}
            </button>
          )}
        </section>
      </div>

      <section className="acct-card">
        <h2>Quick actions</h2>
        <div className="pf-actions">
          <button className="acct-primary" onClick={() => navigate("/dashboard/account")}>Trading Accounts</button>
          <button className="acct-primary" onClick={() => navigate("/dashboard/assets")}>Assets</button>
          <button className="acct-primary" onClick={() => navigate("/dashboard/settings")}>Security</button>
        </div>
      </section>
    </div>
  );
}
