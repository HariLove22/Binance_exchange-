import { useEffect, useState } from "react";
import { api, ApiError, type VipStatus } from "../lib/api";
import "./vip.css";

/**
 * Fee tier (VIP) dashboard: the user's current tier from their trailing-30-day volume, the maker/
 * taker fees it earns, progress to the next tier, and the full tier schedule. Higher volume → lower
 * taker fees, applied automatically on every trade.
 */
export function Vip() {
  const [data, setData] = useState<VipStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.vipMe().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  }, []);

  const progress = data ? Math.round(Number(data.progress) * 100) : 0;

  return (
    <div className="vip">
      <div className="vip-head">
        <h1>Fee Tier</h1>
        <p className="vip-sub">Your VIP level is set by your last-30-day trading volume. It updates automatically.</p>
      </div>
      {err && <p className="vip-err">{err}</p>}

      {data && (
        <>
          <div className="vip-card">
            <div className="vip-current">
              <span className="vip-badge">{data.name}</span>
              <div className="vip-fees">
                <div><span>Maker</span><b>{data.maker_pct}%</b></div>
                <div><span>Taker</span><b>{data.taker_pct}%</b></div>
                <div><span>30d Volume</span><b>${Number(data.volume_30d).toLocaleString(undefined, { maximumFractionDigits: 0 })}</b></div>
              </div>
            </div>

            {data.next_name ? (
              <div className="vip-progress-wrap">
                <div className="vip-progress-label">
                  <span>Progress to {data.next_name}</span>
                  <span>${Number(data.to_next).toLocaleString(undefined, { maximumFractionDigits: 0 })} to go</span>
                </div>
                <div className="vip-bar"><div className="vip-bar-fill" style={{ width: `${progress}%` }} /></div>
              </div>
            ) : (
              <div className="vip-progress-label"><span>You're at the top tier 🎉</span></div>
            )}
          </div>

          <div className="vip-table">
            <div className="vip-h"><span>Tier</span><span className="num">30d Volume ≥</span><span className="num">Maker</span><span className="num">Taker</span></div>
            {data.tiers.map((t) => (
              <div className={`vip-r ${t.level === data.level ? "on" : ""}`} key={t.level}>
                <span>{t.name}{t.level === data.level && <em> · current</em>}</span>
                <span className="num mono">${Number(t.min_volume).toLocaleString()}</span>
                <span className="num mono">{t.maker_pct}%</span>
                <span className="num mono">{t.taker_pct}%</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
