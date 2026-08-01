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
      <div className="ref-hero">
        <h1>Refer friends, earn together 🎉</h1>
        <p>Share your link and earn <b>{data ? Number(data.commission_rate).toFixed(0) : "20"}%</b> of every friend's trading fees — for life. The more they trade, the more you earn.</p>
      </div>

      <div className="ref-steps">
        <GuideStep n={1} title="Share your link"
          body="Copy your unique referral code or link and send it to friends." icon="🔗" />
        <GuideStep n={2} title="Friends sign up & trade"
          body="They join with your code and start trading on Spot or Margin." icon="👥" />
        <GuideStep n={3} title={`Earn ${data ? Number(data.commission_rate).toFixed(0) : "20"}% forever`}
          body="You get a cut of their trading fees, credited straight to your wallet." icon="💰" />
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

function GuideStep({ n, title, body, icon }: { n: number; title: string; body: string; icon: string }) {
  return (
    <div className="ref-step">
      <div className="ref-step-top"><span className="ref-step-n">{n}</span><span className="ref-step-icon">{icon}</span></div>
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}
