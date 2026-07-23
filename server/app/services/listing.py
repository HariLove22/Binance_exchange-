"""On-demand market listing.

The exchange lists only a few pairs for spot with real custody. But we can let a user trade *any*
Binance USDT pair by listing it as a **synthetic** market: the base asset is internal-only (no
chain, no custody, not withdrawable), settlement is in USDT, and the market maker quotes it from
the live price. This is how you offer thousands of instruments without custodying thousands of
coins — the position is a ledger claim settled in the quote asset, exactly like a broker's book.

`ensure_market` is idempotent: if the market already exists it returns it; otherwise, if the symbol
is a real Binance USDT pair, it creates the internal base asset and the market on the fly.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetKind, Market
from app.services import marketdata


class ListingError(Exception):
    pass


def _filters_for(price: float) -> tuple[Decimal, Decimal, Decimal]:
    """Sensible price tick, quantity step and min-notional derived from the price.

    A $60k coin needs a coarse quantity step and a $0.01 tick; a $0.0001 coin needs the reverse.
    These are heuristics, not researched values — good enough to trade a synthetic market.
    """
    if price >= 1000:
        return Decimal("0.01"), Decimal("0.00001"), Decimal("5")
    if price >= 1:
        return Decimal("0.001"), Decimal("0.001"), Decimal("5")
    if price >= 0.01:
        return Decimal("0.00001"), Decimal("1"), Decimal("5")
    return Decimal("0.00000001"), Decimal("10"), Decimal("5")


async def ensure_market(db: AsyncSession, symbol: str) -> Market:
    """Return the market for `symbol`, creating a synthetic one if it is a valid Binance USDT pair."""
    symbol = symbol.upper()
    existing = (await db.execute(select(Market).where(Market.symbol == symbol))).scalar_one_or_none()
    if existing is not None:
        return existing

    # Validate against Binance's real symbol set, and get the base/quote + a live price.
    rows = await marketdata.all_markets(set())
    match = next((r for r in rows if r.symbol == symbol), None)
    if match is None:
        raise ListingError(f"{symbol} is not a tradeable pair on the reference feed")
    if match.quote != "USDT":
        raise ListingError("only USDT-quoted pairs can be listed for synthetic trading")
    if match.price <= 0:
        raise ListingError(f"no live price for {symbol}")

    usdt = (await db.execute(select(Asset).where(Asset.symbol == "USDT"))).scalar_one_or_none()
    if usdt is None:
        raise ListingError("USDT is not listed")

    # Get or create the internal (non-custodial) base asset.
    base = (await db.execute(select(Asset).where(Asset.symbol == match.base))).scalar_one_or_none()
    if base is None:
        base = Asset(
            symbol=match.base, name=match.base, kind=AssetKind.CRYPTO, scale=8,
            enabled=True, custodial=False,  # synthetic — no chain, not withdrawable
        )
        db.add(base)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            base = (await db.execute(select(Asset).where(Asset.symbol == match.base))).scalar_one()

    tick, step, min_notional = _filters_for(match.price)
    market = Market(
        symbol=symbol, base_asset_id=base.id, quote_asset_id=usdt.id,
        price_tick=tick, qty_step=step, min_notional=min_notional,
        maker_fee=Decimal("0.001"), taker_fee=Decimal("0.001"), enabled=True,
    )
    db.add(market)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        market = (await db.execute(select(Market).where(Market.symbol == symbol))).scalar_one()
    return market
