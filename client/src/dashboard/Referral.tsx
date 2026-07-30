import { useEffect, useState } from "react";
import { api, ApiError, type ReferralSummary } from "../lib/api";
import "./referral.css";

/**
 * Referral dashboard: the user's invite code and link, headline stats, and the list of people they
 * referred with what each has earned them. Earnings are a live share of referees' trading fees,
 * credited to the user's spot balance automatically.
 */
export function Referral() {
  const [data, setData] = useState<ReferralSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState<"code" | "link" | null>(null);

  useEffect(() => {
    api.referralMe().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, []);

  const link = data ? `${location.origin}/#/signup?ref=${data.code}` : "";

  function copy(what: "code" | "link", value: string) {
    navigator.clipboard?.writeText(value).then(() => { setCopied(what); setTimeout(() => setCopied(null), 1500); });
  }

  return (
    <div className="ref">
      <div className="ref-head">
        <h1>Referral</h1>
        <p className="ref-sub">Invite friends and earn {data ? Number(data.commission_rate).toFixed(0) : "20"}% of their trading fees, forever.</p>
      </div>

      {err && <p className="ref-err">{err}</p>}

      <div className="ref-stats">
        <Stat label="Total earned" value={data ? `$${Number(data.total_earned_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "—"} />
        <Stat label="Friends referred" value={data ? String(data.count) : "—"} />
        <Stat label="Commission rate" value={data ? `${Number(data.commission_rate).toFixed(0)}%` : "—"} />
      </div>

      <div className="ref-share">
        <div className="ref-field">
          <label>Your referral code</label>
          <div className="ref-copy">
            <span className="ref-code">{data?.code ?? "…"}</span>
            <button onClick={() => data && copy("code", data.code)}>{copied === "code" ? "Copied!" : "Copy"}</button>
          </div>
        </div>
        <div className="ref-field">
          <label>Invite link</label>
          <div className="ref-copy">
            <span className="ref-link">{link || "…"}</span>
            <button onClick={() => copy("link", link)}>{copied === "link" ? "Copied!" : "Copy"}</button>
          </div>
        </div>
      </div>

      <div className="ref-list">
        <h2>Your referrals</h2>
        {data && data.referrals.length === 0 && <p className="ref-empty">No referrals yet. Share your link to start earning.</p>}
        {data && data.referrals.length > 0 && (
          <div className="ref-table">
            <div className="ref-h"><span>Friend</span><span>Joined</span><span className="num">Earned</span></div>
            {data.referrals.map((r, i) => (
              <div className="ref-r" key={i}>
                <span>{r.email}</span>
                <span className="dim">{new Date(r.joined).toLocaleDateString()}</span>
                <span className="num mono">${Number(r.earned_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="ref-stat"><span>{label}</span><b>{value}</b></div>;
}
