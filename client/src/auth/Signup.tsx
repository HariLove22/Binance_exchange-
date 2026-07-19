import { useMemo, useState, type FormEvent } from "react";
import { navigate } from "../router";
import { AuthShell, AuthNotice } from "./components/AuthShell";
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

export function Signup() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [agree, setAgree] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);

  const strength = useMemo(() => scorePassword(password), [password]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (name.trim().length < 2) next.name = "Enter your full name";
    if (!EMAIL_RE.test(email)) next.email = "Enter a valid email address";
    if (password.length < 8) next.password = "Use at least 8 characters";
    if (confirm !== password) next.confirm = "Passwords don't match";
    if (!agree) next.agree = "Please accept the terms to continue";
    setErrors(next);
    setSubmitted(Object.keys(next).length === 0);
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

          <button className="btn btn-primary btn-block" type="submit">
            Create account
          </button>

          <AuthNotice show={submitted} />
        </form>

        <p className="auth-alt">
          Already have an account?{" "}
          <a
            className="auth-link strong"
            href="#/login"
            onClick={(e) => {
              e.preventDefault();
              navigate("login");
            }}
          >
            Log in
          </a>
        </p>
      </div>
    </AuthShell>
  );
}
