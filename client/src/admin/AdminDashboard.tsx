import { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  trimAmount,
  type AdminUserRow,
  type AuthUser,
  type ReconciliationRow,
} from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import "./admin.css";

/**
 * The operator console — a separate dashboard from the user's, shown only to ADMIN accounts.
 *
 * The credit form adds funds to a user through the real deposit flow, so custody sees a matching
 * on-chain deposit and reconciliation stays balanced. The reconciliation panel is the one that
 * matters: it proves the ledger and custody agree, asset by asset.
 */
export function AdminDashboard({ user }: { user: AuthUser }) {
  const { logout } = useAuth();
  const [tab, setTab] = useState<"users" | "reconcile">("users");

  return (
    <div className="admin">
      <header className="admin-top">
        <div className="admin-brand">
          <span className="brand-mark">◈</span> Novex <span className="admin-tag">ADMIN</span>
        </div>
        <div className="admin-top-right">
          <span className="admin-who">{user.email}</span>
          <button className="admin-logout" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>

      <nav className="admin-tabs">
        <button className={tab === "users" ? "active" : ""} onClick={() => setTab("users")}>
          Users &amp; Funds
        </button>
        <button className={tab === "reconcile" ? "active" : ""} onClick={() => setTab("reconcile")}>
          Reconciliation
        </button>
      </nav>

      <main className="admin-main">
        {tab === "users" ? <UsersAndFunds /> : <Reconciliation />}
      </main>
    </div>
  );
}

/* ------------------------------------------------------------- users + credit */

function UsersAndFunds() {
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setUsers(await api.adminUsers());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="admin-grid">
      <section className="admin-card">
        <h2>Add funds to a user</h2>
        <p className="admin-sub">
          Posts through the real deposit flow — a backed credit, not a raw mint, so reconciliation
          stays balanced.
        </p>
        <CreditForm users={users} onDone={load} />
      </section>

      <section className="admin-card">
        <div className="admin-card-head">
          <h2>Users</h2>
          <button className="admin-link" onClick={() => void load()}>
            refresh
          </button>
        </div>
        {error && <p className="admin-error">{error}</p>}
        <div className="admin-table">
          <div className="at-h">
            <span>ID</span>
            <span>Email</span>
            <span>Role</span>
            <span className="num">Assets</span>
          </div>
          {users.map((u) => (
            <div className="at-r" key={u.id}>
              <span className="mono">{u.id}</span>
              <span className="trunc">{u.full_name || u.email}</span>
              <span>
                <span className={`role-chip ${u.role === "ADMIN" ? "admin" : ""}`}>{u.role}</span>
              </span>
              <span className="num">{u.asset_count}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

const ASSETS = ["USDT", "USDC", "ETH", "BNB", "POL", "AVAX", "TRX"];

function CreditForm({ users, onDone }: { users: AdminUserRow[]; onDone: () => void }) {
  const [userId, setUserId] = useState("");
  const [asset, setAsset] = useState("USDT");
  const [amount, setAmount] = useState("1000");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setNote(null);
    try {
      const r = await api.adminCredit({ user_id: Number(userId), asset, amount });
      setNote(`credited ${r.amount} ${r.asset} — deposit #${r.deposit_id} (${r.status})`);
      onDone();
    } catch (err) {
      setNote(err instanceof ApiError ? `${err.status} — ${err.message}` : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="credit-form" onSubmit={submit}>
      <label>
        <span>User</span>
        <select value={userId} onChange={(e) => setUserId(e.target.value)} required>
          <option value="">select…</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              #{u.id} · {u.email}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Asset</span>
        <select value={asset} onChange={(e) => setAsset(e.target.value)}>
          {ASSETS.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Amount</span>
        {/* text, not number: type=number hands back a float and the ledger's precision dies. */}
        <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" required />
      </label>
      <button className="admin-primary" disabled={busy || !userId}>
        {busy ? "…" : "Add funds"}
      </button>
      {note && <p className="admin-note">{note}</p>}
    </form>
  );
}

/* -------------------------------------------------------------- reconciliation */

function Reconciliation() {
  const [rows, setRows] = useState<ReconciliationRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await api.adminReconcile());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = rows.filter((r) => r.custody_onchain !== "0" || r.ledger_external !== "0");
  const broken = rows.filter((r) => !r.balanced);

  return (
    <section className="admin-card wide">
      <div className="admin-card-head">
        <h2>Reconciliation — ledger vs custody</h2>
        <button className="admin-link" onClick={() => void load()}>
          refresh
        </button>
      </div>
      <p className="admin-sub">
        Ledger EXTERNAL (what we say we hold on-chain) against what custody reports holding. Every
        row must balance; a gap means a credit with no funds behind it, or funds moving we did not
        record — both reasons to halt withdrawals.
      </p>

      {error && <p className="admin-error">{error}</p>}

      <div className={`recon-banner ${broken.length ? "bad" : "good"}`}>
        {broken.length === 0
          ? `Balanced — ${active.length} funded asset${active.length === 1 ? "" : "s"} reconcile`
          : `${broken.length} asset(s) DO NOT RECONCILE`}
      </div>

      <div className="admin-table recon">
        <div className="at-h">
          <span>Asset</span>
          <span className="num">Ledger (−EXTERNAL)</span>
          <span className="num">Custody on-chain</span>
          <span>Status</span>
        </div>
        {active.map((r) => (
          <div className="at-r" key={r.asset}>
            <span className="mono">{r.asset}</span>
            <span className="num mono">{trimAmount(r.ledger_external)}</span>
            <span className="num mono">{trimAmount(r.custody_onchain)}</span>
            <span>
              <span className={`role-chip ${r.balanced ? "" : "admin"}`}>
                {r.balanced ? "balanced" : "BROKEN"}
              </span>
            </span>
          </div>
        ))}
        {active.length === 0 && <div className="at-r"><span className="admin-sub">no funded assets yet</span></div>}
      </div>
    </section>
  );
}
