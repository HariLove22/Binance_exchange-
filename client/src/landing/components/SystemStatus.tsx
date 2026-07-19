import { useEffect, useState } from "react";
import { api } from "../../lib/api";

// Preserves the scaffold's original purpose — a live API + DB connectivity check —
// but as a subtle status pill instead of the whole page. Green only when both answer.

type State = "checking" | "ok" | "down";

export function SystemStatus() {
  const [apiState, setApiState] = useState<State>("checking");
  const [dbState, setDbState] = useState<State>("checking");

  useEffect(() => {
    api.health().then(() => setApiState("ok")).catch(() => setApiState("down"));
    api.dbHealth().then(() => setDbState("ok")).catch(() => setDbState("down"));
  }, []);

  const overall: State =
    apiState === "checking" || dbState === "checking"
      ? "checking"
      : apiState === "ok" && dbState === "ok"
        ? "ok"
        : "down";

  const label =
    overall === "ok" ? "All systems operational" : overall === "down" ? "Systems degraded" : "Checking status…";

  return (
    <div className={`status-pill status-${overall}`} title={`API: ${apiState} · DB: ${dbState}`}>
      <span className="status-dot" aria-hidden />
      <span>{label}</span>
    </div>
  );
}
