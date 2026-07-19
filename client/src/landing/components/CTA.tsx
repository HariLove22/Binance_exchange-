import { IconArrow } from "./Icons";

export function CTA() {
  return (
    <section className="cta">
      <div className="cta-card">
        <div className="cta-glow" aria-hidden />
        <h2>Ready to make your first trade?</h2>
        <p>Join the early-access waitlist. Get verified once, and start trading the moment we open.</p>
        <form className="cta-form" onSubmit={(e) => e.preventDefault()}>
          <input type="email" placeholder="you@email.com" aria-label="Email address" required />
          <button className="btn btn-primary btn-lg" type="submit">
            Join waitlist <IconArrow className="ic" />
          </button>
        </form>
        <span className="cta-note">No spam. Unsubscribe anytime.</span>
      </div>
    </section>
  );
}
