import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, trimAmount, type FuturesPosition, type MarketInfo } from "../lib/api";
import { useTicker } from "../lib/useLive";
import "./futures.css";

const LEVERAGES = [1, 2, 3, 5, 10, 20];

function num(s: string | null): string {
  if (s === null) return "—";
  return Number(s).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/**
 * Futures terminal: open leveraged LONG/SHORT positions and track them with live PnL.
 * PnL is polled from the server every 2s — it returns the mark price and unrealized PnL for each
 * open position, so no per-symbol price wiring is needed here.
 */
export function Futures() {
  const [markets, setMarkets] = useState<MarketInfo[]>([]);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [side, setSide] = useState<"LONG" | "SHORT">("LONG");
  const [leverage, setLeverage] = useState(10);
  const [quantity, setQuantity] = useState("");
  const [positions, setPositions] = useState<FuturesPosition[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.marketSymbols().then(setMarkets).catch(() => {});
  }, []);

  // Poll open positions for live PnL (server returns mark + unrealized PnL).
  useEffect(() => {
    let alive = true;
    const load = () => api.futuresPositions().then((p) => alive && setPositions(p)).catch(() => {});
    load();
    const id = setInterval(load, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const ticker = useTicker(symbol);
  const price = ticker?.price ?? null;
  const qty = Number(quantity);
  const marginEst = price && qty > 0 ? (price * qty) / leverage : null;

  async function open(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!(qty > 0)) return setError("Enter a quantity greater than zero");
    setBusy(true);
    try {
      await api.futuresOpen({ symbol, side, leverage: String(leverage), quantity });
      setQuantity("");
      setPositions(await api.futuresPositions());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open position");
    } finally {
      setBusy(false);
    }
  }

  async function close(id: number) {
    setError("");
    try {
      await api.futuresClose(id);
      setPositions(await api.futuresPositions());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not close position");
    }
  }

  return (
    <div className="fut">
      <div className="page-head">
        <h1>Futures</h1>
        <span className="fut-sub">Perpetual · settled at mark price · up to 20x</span>
      </div>

      <div className="fut-grid">
        <form className="fut-form" onSubmit={open}>
          <div className="fut-sides">
            <button type="button" className={`fut-side long ${side === "LONG" ? "on" : ""}`} onClick={() => setSide("LONG")}>
              Long
            </button>
            <button type="button" className={`fut-side short ${side === "SHORT" ? "on" : ""}`} onClick={() => setSide("SHORT")}>
              Short
            </button>
          </div>

          <label className="fut-field">
            <span>Market</span>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {(markets.length ? markets.map((m) => m.symbol) : ["BTCUSDT"]).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>

          <label className="fut-field">
            <span>Leverage <strong>{leverage}x</strong></span>
            <input type="range" min={1} max={20} value={leverage} onChange={(e) => setLeverage(Number(e.target.value))} />
            <div className="fut-lev-marks">
              {LEVERAGES.map((l) => (
                <button type="button" key={l} className={leverage === l ? "on" : ""} onClick={() => setLeverage(l)}>
                  {l}x
                </button>
              ))}
            </div>
          </label>

          <label className="fut-field">
            <span>Quantity (base)</span>
            <input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value.replace(/[^\d.]/g, ""))}
              placeholder="0.00000000"
              inputMode="decimal"
            />
          </label>

          <div className="fut-est">
            <span>Est. margin</span>
            <strong>{marginEst !== null ? `${marginEst.toLocaleString(undefined, { maximumFractionDigits: 2 })} USDT` : "—"}</strong>
          </div>
          {price !== null && (
            <div className="fut-est dim">
              <span>Mark price</span>
              <strong>{price.toLocaleString(undefined, { maximumFractionDigits: 2 })}</strong>
            </div>
          )}

          <button className={`fut-submit ${side.toLowerCase()}`} type="submit" disabled={busy}>
            {busy ? "Opening…" : `Open ${side}`}
          </button>
          {error && <div className="fut-err">{error}</div>}
        </form>

        <div className="fut-positions">
          <h2>Open Positions</h2>
          {positions.length === 0 ? (
            <div className="fut-empty">No open positions.</div>
          ) : (
            <div className="fut-table-wrap">
              <table className="fut-table">
                <thead>
                  <tr>
                    <th>Symbol</th><th>Side</th><th className="r">Size</th><th className="r">Entry</th>
                    <th className="r">Mark</th><th className="r">Lev</th><th className="r">Liq.</th>
                    <th className="r">PnL (USDT)</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const pnl = p.unrealized_pnl !== null ? Number(p.unrealized_pnl) : null;
                    const roi = pnl !== null && Number(p.margin) > 0 ? (pnl / Number(p.margin)) * 100 : null;
                    const cls = pnl === null ? "" : pnl >= 0 ? "up" : "down";
                    return (
                      <tr key={p.id}>
                        <td>{p.symbol}</td>
                        <td className={`fut-dir ${p.side.toLowerCase()}`}>{p.side}</td>
                        <td className="r">{trimAmount(p.size)}</td>
                        <td className="r">{num(p.entry_price)}</td>
                        <td className="r">{num(p.mark_price)}</td>
                        <td className="r">{trimAmount(p.leverage)}x</td>
                        <td className="r fut-liq">{num(p.liquidation_price)}</td>
                        <td className={`r ${cls}`}>
                          {pnl === null ? "—" : `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}`}
                          {roi !== null && <span className="fut-roi"> ({roi >= 0 ? "+" : ""}{roi.toFixed(1)}%)</span>}
                        </td>
                        <td className="r"><button className="fut-close" onClick={() => close(p.id)}>Close</button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
