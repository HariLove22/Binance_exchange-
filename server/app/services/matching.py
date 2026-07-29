"""Wires the pure matcher to the database.

Everything non-deterministic lives here, never in app/engine: loading the book, locking rows,
writing trades, updating statuses. The engine only sees integers.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.matcher import BUY, SELL, Fill, RestingOrder, match
from app.models.order import FILLED, NEW, PARTIALLY_FILLED, Order
from app.models.trade import Trade
from app.services.orderbook import OPEN_STATUSES


async def _opposite_side(db: AsyncSession, pair: str, taker_side: str) -> list[Order]:
    """Load the resting orders a taker could hit, in price-time priority.

    Locked FOR UPDATE: without it two concurrent takers can both read the same resting order,
    both decide it is available, and together fill more than it holds.
    """
    maker_side = SELL if taker_side == BUY else BUY
    # A buyer walks asks from the cheapest up; a seller walks bids from the highest down.
    price_order = Order.price.asc() if taker_side == BUY else Order.price.desc()

    stmt = (
        select(Order)
        .where(
            Order.pair == pair,
            Order.side == maker_side,
            Order.status.in_(OPEN_STATUSES),
        )
        .order_by(price_order, Order.created_at.asc())
        .with_for_update()
    )
    return list(await db.scalars(stmt))


def _status_for(order: Order) -> str:
    if order.filled_quantity >= order.quantity:
        return FILLED
    return PARTIALLY_FILLED if order.filled_quantity > 0 else NEW


async def match_order(db: AsyncSession, taker: Order) -> list[Trade]:
    """Match a freshly created order against the book and persist the result.

    The caller commits. Returns the trades produced (empty if nothing crossed — the order then
    simply rests on the book).
    """
    makers = await _opposite_side(db, taker.pair, taker.side)
    by_id = {m.order_id: m for m in makers}

    fills, _remaining = match(
        taker_side=taker.side,
        taker_price=taker.price,
        taker_quantity=taker.quantity - taker.filled_quantity,
        resting=[
            RestingOrder(m.order_id, m.price, m.quantity - m.filled_quantity) for m in makers
        ],
    )

    trades: list[Trade] = []
    for fill in fills:
        maker = by_id[fill.maker_order_id]

        # Apply the fill to both sides.
        taker.filled_quantity += fill.quantity
        maker.filled_quantity += fill.quantity
        taker.status = _status_for(taker)
        maker.status = _status_for(maker)

        buyer, seller = (taker, maker) if taker.side == BUY else (maker, taker)
        trades.append(
            Trade(
                pair=taker.pair,
                price=fill.price,  # maker's price
                quantity=fill.quantity,
                taker_order_id=taker.order_id,
                maker_order_id=maker.order_id,
                taker_side=taker.side,
                buyer_user_id=buyer.user_id,
                seller_user_id=seller.user_id,
            )
        )

    db.add_all(trades)
    await db.flush()
    return trades


def build_fill_summary(trades: list[Trade]) -> list[Fill]:
    """Shape trades back into fills for the API response."""
    return [
        Fill(maker_order_id=t.maker_order_id, price=t.price, quantity=t.quantity) for t in trades
    ]
