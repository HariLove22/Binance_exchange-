"""USD valuation of assets, from the live Binance reference price.

Shared by margin (leverage/health) and the account overview. Stablecoins are $1; everything else is
its live {SYMBOL}USDT price. Async and network-touching by design — callers inject it into pure
services so those stay deterministic and offline in tests.
"""

from decimal import Decimal

from app.services import marketmaker

STABLE = {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD"}


async def usd_price_of(symbol: str) -> Decimal | None:
    s = (symbol or "").upper()
    if s in STABLE:
        return Decimal("1")
    return await marketmaker.fetch_reference_price(f"{s}USDT")
