"""VIP fee tiers: a user's tier from their 30-day trading volume, and the fee rates it earns.

The exchange charges a taker fee on every fill; a higher tier means a lower rate. A user's tier is
the highest whose volume threshold their trailing-30-day volume clears. Volume is summed from the
trades they were on either side of, valued in quote units (≈ USD for USDT pairs). Thresholds here
are small so the effect is visible on a fresh exchange; scale them up for production.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, Trade


@dataclass(frozen=True)
class Tier:
    level: int
    name: str
    min_volume: Decimal   # trailing-30d volume (quote/USD) to reach this tier
    maker: Decimal        # maker fee rate
    taker: Decimal        # taker fee rate


# Ordered low → high. VIP 0 is the default everyone starts at.
TIERS: list[Tier] = [
    Tier(0, "Regular", Decimal("0"),        Decimal("0.001000"), Decimal("0.001000")),  # 0.100%
    Tier(1, "VIP 1",   Decimal("10000"),    Decimal("0.000900"), Decimal("0.001000")),  # 0.090% / 0.100%
    Tier(2, "VIP 2",   Decimal("100000"),   Decimal("0.000800"), Decimal("0.000900")),
    Tier(3, "VIP 3",   Decimal("1000000"),  Decimal("0.000600"), Decimal("0.000700")),
    Tier(4, "VIP 4",   Decimal("10000000"), Decimal("0.000400"), Decimal("0.000500")),
]


async def thirty_day_volume(db: AsyncSession, user_id: int, now: datetime) -> Decimal:
    """Sum of the quote value of trades the user was on either side of in the last 30 days."""
    since = now - timedelta(days=30)
    as_taker = select(Trade.id).join(Order, Order.id == Trade.taker_order_id).where(
        Order.user_id == user_id, Trade.created_at >= since)
    as_maker = select(Trade.id).join(Order, Order.id == Trade.maker_order_id).where(
        Order.user_id == user_id, Trade.created_at >= since)
    involved = union(as_taker, as_maker).subquery()  # dedup if the user was both sides
    total = (
        await db.execute(
            select(func.coalesce(func.sum(Trade.price * Trade.quantity), 0))
            .where(Trade.id.in_(select(involved)))
        )
    ).scalar()
    return Decimal(total or 0)


def tier_for_volume(volume: Decimal) -> Tier:
    chosen = TIERS[0]
    for t in TIERS:
        if volume >= t.min_volume:
            chosen = t
    return chosen


def next_tier(current: Tier) -> Tier | None:
    return TIERS[current.level + 1] if current.level + 1 < len(TIERS) else None


async def user_tier(db: AsyncSession, user_id: int, now: datetime) -> tuple[Tier, Decimal]:
    volume = await thirty_day_volume(db, user_id, now)
    return tier_for_volume(volume), volume
