import { STATS } from "../data";

export function Stats() {
  return (
    <section className="stats-band">
      <div className="stats-inner">
        {STATS.map((s) => (
          <div className="stat" key={s.label}>
            <strong>{s.value}</strong>
            <span>{s.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
