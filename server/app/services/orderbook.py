"""Order book reads.

Fetches the resting ("open") orders for a pair and returns them in matching order:

  bids — price DESC  (best/highest buyer first)
  asks — price ASC   (best/lowest seller first)

Within a price level the tie-break is `created_at` ASC — the older order fills first. Price
alone is not the whole ordering: **price-time priority** is the actual rule, so the sort has to
carry the time component or the book is in the wrong order the moment two orders share a price.

(When a real sequencer exists, the time key becomes its monotonic sequence number rather than a
timestamp — two orders can land in the same millisecond.)
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import BUY, NEW, PARTIALLY_FILLED, SELL, Order

# "Open" = still resting on the book and able to trade.
OPEN_STATUSES = (NEW, PARTIALLY_FILLED)


async def _side(db: AsyncSession, pair: str, side: str, best_first_desc: bool) -> list[Order]:
    price_order = Order.price.desc() if best_first_desc else Order.price.asc()
    stmt = (
        select(Order)
        .where(Order.pair == pair, Order.side == side, Order.status.in_(OPEN_STATUSES))
        # Sorting in SQL, not Python — this is exactly what ix_orders_pair_status is for.
        .order_by(price_order, Order.created_at.asc())
    )
    return list(await db.scalars(stmt))


async def fetch_order_book(db: AsyncSession, pair: str) -> tuple[list[Order], list[Order]]:
    """Return (bids, asks) for a pair, each already in priority order."""
    bids = await _side(db, pair, BUY, best_first_desc=True)
    asks = await _side(db, pair, SELL, best_first_desc=False)
    return bids, asks
