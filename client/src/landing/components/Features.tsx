import { FEATURES, STEPS } from "../data";
import { FeatureIcon } from "./Icons";

export function Features() {
  return (
    <section className="section" id="features">
      <div className="section-head">
        <h2>Why trade on Novex</h2>
        <p>The parts most exchanges hide — the accounting, the engine, the fees — done right.</p>
      </div>

      <div className="feature-grid">
        {FEATURES.map((f) => (
          <article className="feature-card" key={f.title}>
            <span className="feature-icon">
              <FeatureIcon name={f.icon} className="ic" />
            </span>
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function HowItWorks() {
  return (
    <section className="section" id="how">
      <div className="section-head">
        <h2>Start in three steps</h2>
        <p>From signup to your first trade in minutes.</p>
      </div>

      <div className="steps">
        {STEPS.map((s) => (
          <div className="step" key={s.n}>
            <span className="step-n">{s.n}</span>
            <h3>{s.title}</h3>
            <p>{s.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
