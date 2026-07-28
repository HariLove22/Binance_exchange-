import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import "./account.css";

/**
 * Account settings: the user's profile and security. Email and role are shown but not editable here
 * (role changes are an operator action; email change would need re-verification, which is disabled).
 * Editable now: display name and password. 2FA and KYC are stubbed as the next security steps.
 */
export function Account() {
  const { user } = useAuth();
  if (!user) return null;

  const since = new Date(user.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });

  return (
    <div className="acct">
      <h1>Account</h1>

      <section className="acct-card acct-profile">
        <div className="acct-avatar">{(user.full_name?.[0] ?? user.email[0]).toUpperCase()}</div>
        <div className="acct-id">
          <div className="acct-name">{user.full_name}</div>
          <div className="acct-email">{user.email}</div>
          <div className="acct-badges">
            <span className={`acct-badge ${user.role === "ADMIN" ? "admin" : ""}`}>{user.role}</span>
            <span className={`acct-badge ${user.is_verified ? "ok" : "muted"}`}>
              {user.is_verified ? "Verified" : "Unverified"}
            </span>
          </div>
        </div>
        <div className="acct-meta">
          <div><span>User ID</span><b>#{user.id}</b></div>
          <div><span>Member since</span><b>{since}</b></div>
        </div>
      </section>

      <div className="acct-grid">
        <ProfileForm />
        <PasswordForm />
      </div>

      <section className="acct-card">
        <h2>Security</h2>
        <div className="acct-row">
          <div>
            <div className="acct-row-title">Two-factor authentication (2FA)</div>
            <div className="acct-row-sub">Add an authenticator app for a second layer at login and withdrawal.</div>
          </div>
          <span className="acct-soon">Coming soon</span>
        </div>
        <div className="acct-row">
          <div>
            <div className="acct-row-title">Identity verification (KYC)</div>
            <div className="acct-row-sub">Required for higher limits and fiat withdrawals.</div>
          </div>
          <span className="acct-soon">Coming soon</span>
        </div>
        <div className="acct-row">
          <div>
            <div className="acct-row-title">Email verification</div>
            <div className="acct-row-sub">{user.is_verified ? "Your email is verified." : "Verification is disabled until email service is live."}</div>
          </div>
          <span className={`acct-badge ${user.is_verified ? "ok" : "muted"}`}>{user.is_verified ? "Verified" : "Disabled"}</span>
        </div>
      </section>
    </div>
  );
}

function ProfileForm() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.full_name ?? "");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const changed = name.trim() !== user?.full_name && name.trim().length >= 2;

  async function save() {
    setBusy(true); setErr(null); setNote(null);
    try {
      const updated = await api.updateProfile({ full_name: name.trim() });
      setUser(updated);
      setNote("Profile updated");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <section className="acct-card">
      <h2>Profile</h2>
      <label className="acct-field">
        <span>Display name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
      </label>
      <label className="acct-field">
        <span>Email</span>
        <input value={user?.email ?? ""} readOnly disabled />
      </label>
      {err && <p className="acct-err">{err}</p>}
      {note && <p className="acct-ok">{note}</p>}
      <button className="acct-primary" disabled={!changed || busy} onClick={save}>{busy ? "…" : "Save changes"}</button>
    </section>
  );
}

function PasswordForm() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const strong = next.length >= 8 && /[a-z]/.test(next) && /[A-Z]/.test(next) && /\d/.test(next);
  const ready = cur && strong && next === confirm;

  async function save() {
    setBusy(true); setErr(null); setNote(null);
    try {
      await api.changePassword({ current_password: cur, new_password: next });
      setNote("Password updated");
      setCur(""); setNext(""); setConfirm("");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <section className="acct-card">
      <h2>Change password</h2>
      <label className="acct-field"><span>Current password</span>
        <input type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" />
      </label>
      <label className="acct-field"><span>New password</span>
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
      </label>
      <label className="acct-field"><span>Confirm new password</span>
        <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
      </label>
      <p className={`acct-hint ${next && !strong ? "bad" : ""}`}>At least 8 characters, with an uppercase, a lowercase, and a number.</p>
      {next && confirm && next !== confirm && <p className="acct-err">Passwords don’t match.</p>}
      {err && <p className="acct-err">{err}</p>}
      {note && <p className="acct-ok">{note}</p>}
      <button className="acct-primary" disabled={!ready || busy} onClick={save}>{busy ? "…" : "Update password"}</button>
    </section>
  );
}
