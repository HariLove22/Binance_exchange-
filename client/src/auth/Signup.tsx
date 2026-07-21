import { useMemo, useState, type FormEvent } from "react";
import { navigate } from "../router";
import { useAuth } from "./AuthContext";
import { api, ApiError } from "../lib/api";
import { AuthShell } from "./components/AuthShell";
import { Field } from "./components/Field";
import { SocialButtons } from "./components/SocialButtons";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Cheap client-side strength estimate: length + character variety. 0..4.
function scorePassword(pw: string): number {
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
  return Math.min(s, 4);
}

const STRENGTH_LABELS = ["Too short", "Weak", "Fair", "Good", "Strong"];

// Mirrors the server policy (server is the real gate; this is instant feedback).
function passwordProblem(pw: string): string | undefined {
  if (pw.length < 8) return "Use at least 8 characters";
  if (!/[a-z]/.test(pw)) return "Add a lowercase letter";
  if (!/[A-Z]/.test(pw)) return "Add an uppercase letter";
  if (!/\d/.test(pw)) return "Add a number";
  return undefined;
}

export function Signup() {
  const { login } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [agree, setAgree] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  const strength = useMemo(() => scorePassword(password), [password]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    setNotice("");

    const next: Record<string, string> = {};
    if (name.trim().length < 2) next.name = "Enter your full name";
    if (!EMAIL_RE.test(email)) next.email = "Enter a valid email address";
    const pwProblem = passwordProblem(password);
    if (pwProblem) next.password = pwProblem;
    if (confirm !== password) next.confirm = "Passwords don't match";
    if (!agree) next.agree = "Please accept the terms to continue";
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setLoading(true);
    try {
      const res = await api.register({ email, full_name: name, password });
      if (res.requires_verification) {
        // Only reachable once email verification is enabled server-side.
        setNotice("Account created! Check your email to verify before logging in.");
      } else if (res.access_token) {
        login(res.access_token, res.user);
        navigate("/dashboard");
      }
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell>
      <div className="auth-form-wrap">
        <header className="auth-head">
          <h1>Create your account</h1>
          <p>Sign up in minutes and start trading crypto on Novex.</p>
        </header>

        <SocialButtons />
        <div className="auth-divider"><span>or sign up with email</span></div>

        <form className="auth-form" onSubmit={onSubmit} noValidate>
          {formError && <div className="auth-notice err" role="alert">{formError}</div>}
          {notice && <div className="auth-notice" role="status">{notice}</div>}

          <Field
            id="signup-name"
            label="Full name"
            placeholder="Aarav Sharma"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={errors.name}
          />
          <Field
            id="signup-email"
            label="Email"
            type="email"
            placeholder="you@email.com"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={errors.email}
          />
          <Field
            id="signup-password"
            label="Password"
            type="password"
            placeholder="At least 8 characters"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={errors.password}
            hint="8+ chars with upper, lower & a number"
          />

          {password && (
            <div className={`strength s-${strength}`}>
              <span className="strength-bars">
                {[0, 1, 2, 3].map((i) => (
                  <i key={i} className={i < strength ? "on" : ""} />
                ))}
              </span>
              <span className="strength-label">{STRENGTH_LABELS[strength]}</span>
            </div>
          )}

          <Field
            id="signup-confirm"
            label="Confirm password"
            type="password"
            placeholder="Re-enter your password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            error={errors.confirm}
          />

          <label className={`checkbox terms ${errors.agree ? "err" : ""}`}>
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>
              I agree to the <a className="auth-link" href="#/signup" onClick={(e) => e.preventDefault()}>Terms</a>{" "}
              and <a className="auth-link" href="#/signup" onClick={(e) => e.preventDefault()}>Privacy Policy</a>
            </span>
          </label>
          {errors.agree && <span className="field-msg err">{errors.agree}</span>}

          <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>

        <p className="auth-alt">
          Already have an account?{" "}
          <a
            className="auth-link strong"
            href="#/login"
            onClick={(e) => {
              e.preventDefault();
              navigate("/login");
            }}
          >
            Log in
          </a>
        </p>
      </div>
    </AuthShell>
  );
}
