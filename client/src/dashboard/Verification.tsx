import { useEffect, useState } from "react";
import { api, ApiError, type KycStatus } from "../lib/api";
import { fileToDownscaledDataUrl } from "../lib/image";
import { navigate } from "../router";
import "./verification.css";

const ID_TYPES = [
  ["PASSPORT", "Passport"],
  ["NATIONAL_ID", "National ID"],
  ["DRIVERS_LICENSE", "Driver’s License"],
] as const;

const COUNTRIES = ["India", "United States", "United Kingdom", "United Arab Emirates", "Singapore", "Germany", "Australia", "Canada", "Other"];

/**
 * Identity verification (KYC). Shows the current status and, when not yet approved or pending, a
 * form to submit identity details. Submitting moves the application to PENDING for an operator to
 * review. Approval unlocks higher limits (tracked here; enforcement is a later step).
 */
export function Verification() {
  const [kyc, setKyc] = useState<KycStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.kycMe().then(setKyc).catch((e) => setErr(e instanceof ApiError ? e.message : String(e)));
  useEffect(() => { load(); }, []);

  return (
    <div className="kyc">
      <div className="kyc-head">
        <button className="kyc-back" onClick={() => navigate("/dashboard")}>← Back</button>
        <h1>Identity Verification</h1>
        <p className="kyc-sub">Verify your identity (KYC) to unlock higher limits and full access.</p>
      </div>

      {err && <p className="kyc-err">{err}</p>}
      {kyc && <StatusBanner kyc={kyc} />}

      {kyc && (kyc.status === "NOT_STARTED" || kyc.status === "REJECTED") && (
        <KycForm onDone={load} />
      )}
    </div>
  );
}

function StatusBanner({ kyc }: { kyc: KycStatus }) {
  const meta: Record<string, { cls: string; title: string; body: string }> = {
    NOT_STARTED: { cls: "muted", title: "Not verified", body: "Submit your identity details below to get started." },
    PENDING: { cls: "pending", title: "Under review", body: "Your application is being reviewed. This usually takes a few minutes." },
    APPROVED: { cls: "ok", title: "Verified ✓", body: `You're verified${kyc.legal_name ? ` as ${kyc.legal_name}` : ""}. Higher limits are unlocked.` },
    REJECTED: { cls: "bad", title: "Rejected", body: kyc.reject_reason || "Your application was rejected. Please correct your details and resubmit." },
  };
  const m = meta[kyc.status];
  return (
    <div className={`kyc-banner ${m.cls}`}>
      <div className="kyc-banner-title">{m.title}</div>
      <div className="kyc-banner-body">{m.body}</div>
    </div>
  );
}

function KycForm({ onDone }: { onDone: () => void }) {
  const [legalName, setLegalName] = useState("");
  const [dob, setDob] = useState("");
  const [country, setCountry] = useState("India");
  const [idType, setIdType] = useState("PASSPORT");
  const [idNumber, setIdNumber] = useState("");
  const [front, setFront] = useState<string | null>(null);
  const [back, setBack] = useState<string | null>(null);
  const [selfie, setSelfie] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const ready = legalName.trim().length >= 2 && dob && idNumber.trim().length >= 4 && !!front;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.kycSubmit({
        legal_name: legalName.trim(), date_of_birth: dob, country, id_type: idType, id_number: idNumber.trim(),
        doc_front: front, doc_back: back, selfie,
      });
      window.dispatchEvent(new CustomEvent("kyc-changed"));
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <form className="kyc-card" onSubmit={submit}>
      <h2>Submit your details</h2>
      <div className="kyc-grid">
        <label className="wide">Full legal name
          <input value={legalName} onChange={(e) => setLegalName(e.target.value)} placeholder="As on your ID" maxLength={120} />
        </label>
        <label>Date of birth
          <input type="date" value={dob} onChange={(e) => setDob(e.target.value)} max={new Date().toISOString().slice(0, 10)} />
        </label>
        <label>Country
          <select value={country} onChange={(e) => setCountry(e.target.value)}>{COUNTRIES.map((c) => <option key={c}>{c}</option>)}</select>
        </label>
        <label>ID type
          <select value={idType} onChange={(e) => setIdType(e.target.value)}>{ID_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label>ID number
          <input value={idNumber} onChange={(e) => setIdNumber(e.target.value)} placeholder="Document number" maxLength={64} />
        </label>
      </div>

      <h3 className="kyc-docs-title">Upload documents</h3>
      <div className="kyc-uploads">
        <DocUpload label="ID front" required value={front} onChange={setFront} onErr={setErr} />
        <DocUpload label="ID back" value={back} onChange={setBack} onErr={setErr} />
        <DocUpload label="Selfie" value={selfie} onChange={setSelfie} onErr={setErr} />
      </div>

      <p className="kyc-note">Photos are downscaled in your browser before upload. Demo only — no real identity check runs; an operator reviews and approves the submission.</p>
      {err && <p className="kyc-err">{err}</p>}
      <button className="kyc-submit" disabled={!ready || busy}>{busy ? "…" : "Submit for verification"}</button>
    </form>
  );
}

function DocUpload({ label, required, value, onChange, onErr }: {
  label: string; required?: boolean; value: string | null; onChange: (v: string | null) => void; onErr: (e: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try { onChange(await fileToDownscaledDataUrl(file)); }
    catch (err) { onErr(err instanceof Error ? err.message : String(err)); }
    finally { setLoading(false); }
  }
  return (
    <label className={`kyc-upload ${value ? "has" : ""}`}>
      {value
        ? <img src={value} alt={label} className="kyc-upload-img" />
        : <span className="kyc-upload-ph">{loading ? "…" : `+ ${label}${required ? " *" : ""}`}</span>}
      <input type="file" accept="image/*" onChange={pick} hidden />
      {value && <span className="kyc-upload-name">{label} ✓ — change</span>}
    </label>
  );
}
