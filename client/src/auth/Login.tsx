import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { currentQuery, navigate } from "../router";
import { useAuth } from "./AuthContext";
import { api, ApiError } from "../lib/api";
import { AuthShell } from "./components/AuthShell";
import { Field } from "./components/Field";
import { SocialButtons } from "./components/SocialButtons";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState("");
  const [loading, setLoading] = useState(false);
  // Set once on mount: "?registered=1" means they just came from a successful signup.
  const [justRegistered] = useState(() => currentQuery().get("registered") === "1");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");

    const next: typeof errors = {};
    if (!EMAIL_RE.test(email)) next.email = t("auth.invalidEmail");
    if (!password) next.password = t("auth.enterPassword");
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
      setFormError(err instanceof ApiError ? err.message : t("auth.genericError"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell>
      <div className="auth-form-wrap">
        <header className="auth-head">
          <h1>{t("auth.welcomeBack")}</h1>
          <p>{t("auth.loginSubtitle")}</p>
        </header>

        <SocialButtons />
        <div className="auth-divider"><span>{t("auth.orContinueEmail")}</span></div>

        <form className="auth-form" onSubmit={onSubmit} noValidate>
          {justRegistered && !formError && (
            <div className="auth-notice ok" role="status">
              {t("auth.accountCreated")}
            </div>
          )}
          {formError && <div className="auth-notice err" role="alert">{formError}</div>}

          <Field
            id="login-email"
            label={t("auth.email")}
            type="email"
            placeholder={t("auth.emailPlaceholder")}
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            error={errors.email}
          />
          <Field
            id="login-password"
            label={t("auth.password")}
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
              <span>{t("auth.rememberMe")}</span>
            </label>
            <a className="auth-link" href="#/login" onClick={(e) => e.preventDefault()}>
              {t("auth.forgotPassword")}
            </a>
          </div>

          <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
            {loading ? t("auth.loggingIn") : t("auth.login")}
          </button>
        </form>

        <p className="auth-alt">
          {t("auth.newToNovex")}{" "}
          <a
            className="auth-link strong"
            href="#/signup"
            onClick={(e) => {
              e.preventDefault();
              navigate("/signup");
            }}
          >
            {t("auth.createAccount")}
          </a>
        </p>
      </div>
    </AuthShell>
  );
}
