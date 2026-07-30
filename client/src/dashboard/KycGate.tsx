import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { navigate } from "../router";
import "./kycgate.css";

/** Whether the current user is KYC-approved. `null` while loading. Re-checks on `kyc-changed`. */
export function useKycApproved(): boolean | null {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.kycMe().then((k) => live && setOk(k.status === "APPROVED")).catch(() => live && setOk(false));
    load();
    window.addEventListener("kyc-changed", load);
    return () => { live = false; window.removeEventListener("kyc-changed", load); };
  }, []);
  return ok;
}

/** Shown in place of an order form when the user hasn't passed KYC. Trading is blocked until then. */
export function KycRequiredNotice() {
  return (
    <div className="kyc-gate">
      <div className="kyc-gate-icon">🔒</div>
      <div className="kyc-gate-title">Verify your identity to trade</div>
      <p className="kyc-gate-body">Complete identity verification (KYC) to unlock trading. It only takes a minute.</p>
      <button className="kyc-gate-btn" onClick={() => navigate("/dashboard/verification")}>Verify Now</button>
    </div>
  );
}

/** A dismissible modal prompt — used when a trade attempt is blocked by the backend (403). */
export function KycPrompt({ onClose }: { onClose: () => void }) {
  return (
    <div className="kyc-modal" onClick={onClose}>
      <div className="kyc-modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="kyc-gate-icon">🔒</div>
        <h3>KYC verification required</h3>
        <p>You need to complete identity verification before you can trade.</p>
        <div className="kyc-modal-acts">
          <button className="kyc-modal-ghost" onClick={onClose}>Later</button>
          <button className="kyc-gate-btn" onClick={() => navigate("/dashboard/verification")}>Verify Now</button>
        </div>
      </div>
    </div>
  );
}
