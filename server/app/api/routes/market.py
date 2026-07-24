"""Public market data.

The order book is public on every real exchange — you can see the market before you have an
account — so this endpoint is deliberately unauthenticated.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import UnknownAsset, split_pair
from app.core.db import get_db
from app.core.money import format_money, from_scaled_int
from app.models.order import DEFAULT_PAIR, Order
from app.schemas.orderbook import OrderBookEntry, OrderBookResponse
from app.services.orderbook import fetch_order_book

router = APIRouter(prefix="/market", tags=["market"])


def _fmt(units: int, scale: int) -> str:
    return format_money(from_scaled_int(units, scale), scale)


def _entry(order: Order, price_scale: int, qty_scale: int) -> OrderBookEntry:
    return OrderBookEntry(
        order_id=order.order_id,
        price=_fmt(order.price, price_scale),
        # The REMAINING quantity, not the original. A partially filled order still rests on
        # the book, but only for what is left of it — showing `quantity` here would overstate
        # available liquidity and let a taker plan against size that no longer exists.
        quantity=_fmt(order.quantity - order.filled_quantity, qty_scale),
        created_at=order.created_at,
    )


@router.get("/orderbook", response_model=OrderBookResponse)
async def orderbook(
    pair: str = Query(default=DEFAULT_PAIR),
    db: AsyncSession = Depends(get_db),
) -> OrderBookResponse:
    try:
        base, quote = split_pair(pair)
    except UnknownAsset as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    bids, asks = await fetch_order_book(db, pair)

    # Both sides come back already sorted, so the top of each list is the best price.
    best_bid = bids[0].price if bids else None
    best_ask = asks[0].price if asks else None

    return OrderBookResponse(
        pair=pair,
        bids=[_entry(o, quote.scale, base.scale) for o in bids],
        asks=[_entry(o, quote.scale, base.scale) for o in asks],
        best_bid=_fmt(best_bid, quote.scale) if best_bid is not None else None,
        best_ask=_fmt(best_ask, quote.scale) if best_ask is not None else None,
        spread=(
            _fmt(best_ask - best_bid, quote.scale)
            if best_bid is not None and best_ask is not None
            else None
        ),
    )
