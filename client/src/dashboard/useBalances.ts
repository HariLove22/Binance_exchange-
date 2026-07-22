import { useCallback, useEffect, useState } from "react";
import { api, type Balance } from "../lib/api";

export function useBalances() {
  const [balances, setBalances] = useState<Balance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setError("");
    try {
      const res = await api.balances();
      setBalances(res.balances);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load balances");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { balances, loading, error, reload };
}

/** True when the string amount is not zero — avoids parseFloat on money for display logic. */
export function isNonZero(amount: string): boolean {
  return /[1-9]/.test(amount);
}
