"""The full market universe, proxied and cached from Binance's public feed.

Binance lists thousands of pairs across many quote segments (USDT, USDC, BTC, BNB, FDUSD…). We
show all of them so the market list looks like a real exchange's — but only the pairs we have a
market for can actually be traded here, because trading needs the base asset in our ledger, our
matching engine, and market-maker liquidity. We cannot custody thousands of coins. So each row is
flagged `tradeable`: the ones we list are clickable-to-trade, the rest are view-only (their chart
still works, since the chart is Binance's datafeed).

Two upstream calls, cached with different lifetimes:
  - exchangeInfo → symbol -> (base, quote, status). Rarely changes; cached for an hour.
  - ticker/24hr  → live-ish price and 24h stats for every symbol. Cached for a few seconds so we
    serve the browser fast and do not hammer Binance once per page load.
"""

import asyncio
import time
from dataclasses import dataclass

import httpx

BINANCE = "https://data-api.binance.vision/api/v3"

_EXCHANGE_TTL = 3600.0
_TICKER_TTL = 8.0

_exchange: dict | None = None
_exchange_at = 0.0
_ticker: list | None = None
_ticker_at = 0.0
_lock = asyncio.Lock()


@dataclass(frozen=True)
class MarketRow:
    symbol: str
    base: str
    quote: str
    price: float
    change_percent: float
    quote_volume: float
    tradeable: bool


async def _get(client: httpx.AsyncClient, path: str) -> object:
    resp = await client.get(f"{BINANCE}{path}", timeout=12.0)
    resp.raise_for_status()
    return resp.json()


async def _refresh() -> None:
    global _exchange, _exchange_at, _ticker, _ticker_at
    now = time.monotonic()
    need_exchange = _exchange is None or now - _exchange_at > _EXCHANGE_TTL
    need_ticker = _ticker is None or now - _ticker_at > _TICKER_TTL
    if not need_exchange and not need_ticker:
        return

    async with _lock:
        now = time.monotonic()
        async with httpx.AsyncClient() as client:
            if _exchange is None or now - _exchange_at > _EXCHANGE_TTL:
                data = await _get(client, "/exchangeInfo")
                _exchange = {
                    s["symbol"]: (s["baseAsset"], s["quoteAsset"])
                    for s in data["symbols"]
                    if s.get("status") == "TRADING"
                }
                _exchange_at = now
            if _ticker is None or now - _ticker_at > _TICKER_TTL:
                _ticker = await _get(client, "/ticker/24hr")
                _ticker_at = now


async def all_markets(tradeable: set[str]) -> list[MarketRow]:
    """Every TRADING pair with live 24h stats, flagged by whether we list it for trading."""
    await _refresh()
    if _exchange is None or _ticker is None:
        return []

    rows: list[MarketRow] = []
    for t in _ticker:
        sym = t["symbol"]
        pair = _exchange.get(sym)
        if pair is None:
            continue
        base, quote = pair
        try:
            rows.append(
                MarketRow(
                    symbol=sym, base=base, quote=quote,
                    price=float(t["lastPrice"]),
                    change_percent=float(t["priceChangePercent"]),
                    quote_volume=float(t["quoteVolume"]),
                    tradeable=sym in tradeable,
                )
            )
        except (KeyError, ValueError):
            continue

    # Our tradeable pairs first, then by 24h quote volume — the busiest markets on top, like
    # Binance defaults to.
    rows.sort(key=lambda r: (not r.tradeable, -r.quote_volume))
    return rows


# The segments Binance surfaces as market tabs — the crypto and stablecoin quotes, in the order it
# shows them. Fiat quotes (TRY, IDR, BRL…) dominate by nominal volume but are not what the tabs are
# for, so they are not promoted.
_PREFERRED_SEGMENTS = ["USDT", "USDC", "FDUSD", "BTC", "BNB", "ETH", "TUSD", "TRY", "EUR"]


def quote_segments(rows: list[MarketRow]) -> list[str]:
    """The quote-asset tabs to show: the preferred crypto/stable quotes that actually exist."""
    present = {r.quote for r in rows}
    return [q for q in _PREFERRED_SEGMENTS if q in present]
