// Decorative OAuth buttons. Wire to real providers when auth lands.

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
    <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.88 2.68-6.62z" />
    <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
    <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3-2.33z" />
    <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.47.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
  </svg>
);

const AppleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor" aria-hidden>
    <path d="M13.5 9.6c0-1.9 1.55-2.82 1.62-2.86-.88-1.3-2.26-1.47-2.75-1.49-1.17-.12-2.28.69-2.87.69-.59 0-1.5-.67-2.47-.65-1.27.02-2.44.74-3.09 1.87-1.32 2.29-.34 5.68.94 7.54.63.9 1.37 1.92 2.34 1.88.94-.04 1.3-.61 2.43-.61 1.14 0 1.46.61 2.46.59 1.02-.02 1.66-.92 2.28-1.83.72-1.05 1.02-2.06 1.03-2.11-.02-.01-1.97-.76-1.99-3zM11.7 3.9c.52-.63.87-1.5.77-2.38-.75.03-1.65.5-2.19 1.13-.48.55-.9 1.44-.79 2.29.83.07 1.68-.42 2.2-1.04z" />
  </svg>
);

export function SocialButtons() {
  return (
    <div className="social-buttons">
      <button type="button" className="btn btn-social">
        <GoogleIcon /> Google
      </button>
      <button type="button" className="btn btn-social">
        <AppleIcon /> Apple
      </button>
    </div>
  );
}
