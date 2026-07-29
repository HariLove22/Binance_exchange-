import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, trimAmount, type OrderRow } from "../lib/api";

/**
 * One place for all of a user's orders, split by a tab: Open (still working, cancellable), Filled,
 * and Cancelled. Replaces the two separate "open orders" and "history" tables.
 *
 * Single source: GET /trade/orders?include_history=true returns every order the user has, open and
 * closed, so the tabs are just a client-side filter over one fetch. The Open tab carries the Cancel
 * action; the finished tabs don't.
 *
 * `oh-` class prefix keeps these off trade.css's app-wide order classes so its rules can't bleed in.
 */

type Tab = "all" | "open" | "filled" | "cancelled";
type SortOrder = "newest" | "oldest";

// Still-working statuses = "Open". Everything else is terminal (history).
const OPEN = new Set(["NEW", "PARTIALLY_FILLED"]);

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "filled", label: "Filled" },
  { key: "cancelled", label: "Cancelled" },
];

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function MyOrders({
  /** Bump to refetch — e.g. after the form places an order. */
  refreshToken = 0,
  /** Called after a successful cancel so the parent can refresh balance/book. */
  onChanged,
}: {
  refreshToken?: number;
  onChanged?: () => void;
}) {
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("open");
  const [sort, setSort] = useState<SortOrder>("newest");
  const [cancelling, setCancelling] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      setOrders(await api.orderHistory()); // include_history=true → open + closed
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load your orders");
      setOrders([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  async function cancel(id: number) {
    setCancelling(id);
    setError("");
    try {
      await api.cancelOrder(id);
      await load();
      onChanged?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not cancel the order");
    } finally {
      setCancelling(null);
    }
  }

  const openCount = (orders ?? []).filter((o) => OPEN.has(o.status)).length;

  const rows = useMemo(() => {
    const filtered = (orders ?? []).filter((o) => {
      if (tab === "all") return true;
      if (tab === "open") return OPEN.has(o.status);
      if (tab === "filled") return o.status === "FILLED";
      return o.status === "CANCELED";
    });
    // created_at is ISO 8601, so a string compare is chronological.
    filtered.sort((a, b) => {
      const cmp = a.created_at.localeCompare(b.created_at);
      return sort === "newest" ? -cmp : cmp;
    });
    return filtered;
  }, [orders, tab, sort]);

  const emptyText =
    tab === "all"
      ? "No orders yet."
      : tab === "open"
        ? "No open orders."
        : tab === "filled"
          ? "No filled orders yet."
          : "No cancelled orders.";

  return (
    <div className="oh">
      <div className="oh-head">
        <h2>My Orders</h2>
        <div className="oh-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`oh-tab ${tab === t.key ? "on" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
              {t.key === "open" && openCount > 0 && <span className="oh-badge">{openCount}</span>}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="oh-sort"
          onClick={() => setSort((s) => (s === "newest" ? "oldest" : "newest"))}
          title="Toggle date order"
        >
          {sort === "newest" ? "Newest first ↓" : "Oldest first ↑"}
        </button>
      </div>

      {error && <div className="oh-msg err">{error}</div>}

      {orders === null ? (
        <div className="oh-msg">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="oh-msg">{emptyText}</div>
      ) : (
        <div className="oh-table">
          <div className="oh-cols">
            <span>Date</span>
            <span>Pair</span>
            <span>Side</span>
            <span>Type</span>
            <span className="r">Price</span>
            <span className="r">Quantity</span>
            <span className="r">Filled</span>
            <span>Status</span>
            <span className="r">Action</span>
          </div>
          {rows.map((o) => {
            const isOpen = OPEN.has(o.status);
            return (
              <div className="oh-row" key={o.id}>
                <span className="oh-date">{formatDate(o.created_at)}</span>
                <span className="oh-pair">{o.symbol}</span>
                <span className={`oh-side ${o.side.toLowerCase()}`}>{o.side}</span>
                <span className="oh-type">{o.type}</span>
                <span className="r oh-num">{o.price ? trimAmount(o.price) : "Market"}</span>
                <span className="r oh-num">{trimAmount(o.quantity)}</span>
                <span className="r oh-num oh-filled">
                  {trimAmount(o.filled_quantity)}
                  <em> / {trimAmount(o.quantity)}</em>
                </span>
                <span className={`oh-status ${o.status.toLowerCase()}`}>
                  {o.status.replace(/_/g, " ")}
                </span>
                <span className="r">
                  {isOpen ? (
                    <button
                      className="oh-cancel"
                      disabled={cancelling === o.id}
                      onClick={() => void cancel(o.id)}
                    >
                      {cancelling === o.id ? "…" : "Cancel"}
                    </button>
                  ) : (
                    <span className="oh-dash">—</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
