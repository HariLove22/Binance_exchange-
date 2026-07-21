import { useState, type FormEvent } from "react";
import { navigate } from "../router";
import { useAuth } from "./AuthContext";
import { api, ApiError } from "../lib/api";
import { AuthShell } from "./components/AuthShell";
import { Field } from "./components/Field";
import { SocialButtons } from "./components/SocialButtons";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");

    const next: typeof errors = {};
    if (!EMAIL_RE.test(email)) next.email = "Enter a valid email address";
    if (!password) next.password = "Enter your password";
    setErrors(next);
    if (Object.keys(next).length > 0) return;

    setLoading(true);
    try {
      const res = await api.login({ email, password });
      if (res.access_token) {
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
          <h1>Welcome back</h1>
          <p>Log in to your Novex account to keep trading.</p>
        </header>

        <SocialButtons />
        <div className="auth-divider"><span>or continue with email</span></div>

        <form className="auth-form" onSubmit={onSubmit} noValidate>
          {formError && <div className="auth-notice err" role="alert">{formError}</div>}

          <Field
            id="login-email"
            label="Email"
            type="email"
            placeholder="you@email.com"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={errors.email}
          />
          <Field
            id="login-password"
            label="Password"
            type="password"
            placeholder="••••••••"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={errors.password}
          />

          <div className="auth-row">
            <label className="checkbox">
              <input type="checkbox" defaultChecked />
              <span>Remember me</span>
            </label>
            <a className="auth-link" href="#/login" onClick={(e) => e.preventDefault()}>
              Forgot password?
            </a>
          </div>

          <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
            {loading ? "Logging in…" : "Log in"}
          </button>
        </form>

        <p className="auth-alt">
          New to Novex?{" "}
          <a
            className="auth-link strong"
            href="#/signup"
            onClick={(e) => {
              e.preventDefault();
              navigate("/signup");
            }}
          >
            Create an account
          </a>
        </p>
      </div>
    </AuthShell>
  );
}
