import { useEffect, useState } from "react";
import { api, ApiError, type RewardsResponse } from "../lib/api";
import { navigate } from "../router";
import "./rewards.css";

/**
 * Rewards Hub: onboarding tasks that pay a small USDT reward. Each task's progress is checked against
 * real state; a completed task can be claimed once, crediting the reward to the spot wallet.
 */
export function Rewards() {
  const [data, setData] = useState<RewardsResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = () => api.rewardsMe().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  useEffect(() => { load(); }, []);

  async function claim(id: string) {
    setBusy(id); setErr(null); setNote(null);
    try {
      const r = await api.rewardsClaim(id);
      setData(r);
      setNote("Reward credited to your spot wallet 🎉");
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(null); }
  }

  const goFor: Record<string, string> = {
    verify_kyc: "/dashboard/verification", first_deposit: "/dashboard/assets",
    first_trade: "/dashboard/trade", open_margin: "/dashboard/margin", refer_friend: "/dashboard/referral",
  };

  return (
    <div className="rw">
      <div className="rw-head">
        <div>
          <h1>Rewards Hub</h1>
          <p className="rw-sub">Complete tasks to earn {data?.reward_asset ?? "USDT"} rewards, credited straight to your wallet.</p>
        </div>
        {data && (
          <div className="rw-total">
            <span>Total earned</span>
            <b>{Number(data.total_claimed).toLocaleString()} {data.reward_asset}</b>
          </div>
        )}
      </div>

      {err && <p className="rw-err">{err}</p>}
      {note && <p className="rw-note">{note}</p>}

      <div className="rw-grid">
        {data?.tasks.map((t) => (
          <div className={`rw-card ${t.claimed ? "done" : t.completed ? "ready" : ""}`} key={t.id}>
            <div className="rw-reward">+{t.reward} {data.reward_asset}</div>
            <h3>{t.title}</h3>
            <p>{t.description}</p>
            <div className="rw-cta">
              {t.claimed ? (
                <span className="rw-claimed">✓ Claimed</span>
              ) : t.completed ? (
                <button className="rw-claim" disabled={busy === t.id} onClick={() => claim(t.id)}>{busy === t.id ? "…" : "Claim"}</button>
              ) : (
                <button className="rw-go" onClick={() => navigate(goFor[t.id] ?? "/dashboard")}>Go →</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
