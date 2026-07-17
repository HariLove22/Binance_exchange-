import { useEffect, useState } from "react";
import { api } from "./lib/api";
import "./App.css";

type Check = {
  label: string;
  state: "checking" | "ok" | "failed";
  detail?: string;
};

const INITIAL: Check[] = [
  { label: "API", state: "checking" },
  { label: "Database", state: "checking" },
];

function App() {
  const [checks, setChecks] = useState<Check[]>(INITIAL);

  useEffect(() => {
    const update = (i: number, next: Omit<Check, "label">) =>
      setChecks((prev) =>
        prev.map((c, idx) => (idx === i ? { ...c, ...next } : c)),
      );

    api
      .health()
      .then((r) => update(0, { state: "ok", detail: r.environment }))
      .catch((e: Error) => update(0, { state: "failed", detail: e.message }));

    api
      .dbHealth()
      .then((r) => update(1, { state: "ok", detail: r.database }))
      .catch((e: Error) => update(1, { state: "failed", detail: e.message }));
  }, []);

  return (
    <main className="shell">
      <h1>Exchange</h1>
      <p className="sub">Scaffold — stack connectivity check</p>

      <ul className="checks">
        {checks.map((c) => (
          <li key={c.label} className={c.state}>
            <span className="dot" aria-hidden />
            <span className="name">{c.label}</span>
            <span className="detail">{c.detail ?? c.state}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}

export default App;
