"""Trading endpoints: place and cancel orders, list open orders and fills.

Placing an order runs the full path — validate, lock funds, match, settle — inside one request and
one database transaction. If anything raises, the transaction rolls back and no funds moved.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import (
    Asset,
    CANCELLABLE_STATUSES,
    Market,
    OPEN_STATUSES,
    STOP_TYPES,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Trade,
    User,
)
from app.services import listing, marketmaker, pubsub, trading
from app.services.listing import ListingError
from app.services.trading import TradingError

router = APIRouter(prefix="/trade", tags=["trade"])


def _dev_only() -> None:
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "dev-only endpoint")


class OrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: str
    price: str | None = None
    # Stop (STOP_LIMIT / STOP_MARKET) only: the level that arms the order.
    trigger_price: str | None = None


class OrderResponse(BaseModel):
    id: int
    symbol: str
    side: str
    type: str
    price: str | None
    trigger_price: str | None
    quantity: str
    filled_quantity: str
    status: str


def _order_response(order: Order, symbol: str) -> OrderResponse:
    return OrderResponse(
        id=order.id, symbol=symbol, side=order.side.value, type=order.type.value,
        price=f"{order.price.normalize():f}" if order.price is not None else None,
        trigger_price=f"{order.trigger_price.normalize():f}" if order.trigger_price is not None else None,
        quantity=f"{order.quantity.normalize():f}", filled_quantity=f"{order.filled_quantity.normalize():f}",
        status=order.status.value,
    )


async def _market(db: AsyncSession, symbol: str) -> Market:
    market = (await db.execute(select(Market).where(Market.symbol == symbol.upper()))).scalar_one_or_none()
    if market is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown market {symbol!r}")
    return market


@router.post("/order", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(
    body: OrderRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    market = await _market(db, body.symbol)
    try:
        quantity = Decimal(body.quantity)
        price = Decimal(body.price) if body.price is not None else None
        trigger_price = Decimal(body.trigger_price) if body.trigger_price is not None else None
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad number") from None

    try:
        if body.type in STOP_TYPES:
            if trigger_price is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "stop order needs a trigger_price")
            reference = await marketmaker.fetch_reference_price(market.symbol)
            if reference is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "no reference price to arm the stop")
            order = await trading.place_stop_order(
                db, user_id=user.id, market=market, side=body.side, order_type=body.type,
                quantity=quantity, trigger_price=trigger_price, reference_price=reference, price=price,
            )
        else:
            order = (await trading.place_order(
                db, user_id=user.id, market=market, side=body.side,
                order_type=body.type, quantity=quantity, price=price,
            )).order
    except TradingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    pubsub.publish(pubsub.market_channel(market.symbol))  # wake live subscribers
    return _order_response(order, market.symbol)


@router.delete("/order/{order_id}", response_model=OrderResponse)
async def cancel_order(
    order_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        order = await trading.cancel_order(db, user_id=user.id, order_id=order_id)
    except TradingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    market = await db.get(Market, order.market_id)
    await db.commit()
    pubsub.publish(pubsub.market_channel(market.symbol))
    return _order_response(order, market.symbol)


@router.get("/orders", response_model=list[OrderResponse])
async def open_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    include_history: bool = Query(False),
):
    q = select(Order, Market.symbol).join(Market, Market.id == Order.market_id).where(Order.user_id == user.id)
    if not include_history:
        # Open = resting book orders and un-triggered stops (both are still live and cancellable).
        q = q.where(Order.status.in_(CANCELLABLE_STATUSES))
    q = q.order_by(Order.id.desc()).limit(100)
    return [_order_response(o, sym) for o, sym in (await db.execute(q)).all()]


class MyTrade(BaseModel):
    id: int
    symbol: str
    price: str
    quantity: str
    side: str  # this user's side
    role: str  # maker | taker
    created_at: str


@router.get("/mytrades", response_model=list[MyTrade])
async def my_trades(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Trade, Market.symbol, Order.user_id.label("maker_uid"))
            .join(Market, Market.id == Trade.market_id)
            .join(Order, Order.id == Trade.maker_order_id)
            .order_by(Trade.id.desc())
            .limit(200)
        )
    ).all()
    # Filter to trades this user was on either side of, and label their side/role.
    taker_uids = dict(
        (
            await db.execute(
                select(Trade.id, Order.user_id).join(Order, Order.id == Trade.taker_order_id)
            )
        ).all()
    )
    out: list[MyTrade] = []
    for t, symbol, maker_uid in rows:
        taker_uid = taker_uids.get(t.id)
        if user.id not in (maker_uid, taker_uid):
            continue
        is_taker = user.id == taker_uid
        user_side = t.taker_side if is_taker else (OrderSide.SELL if t.taker_side is OrderSide.BUY else OrderSide.BUY)
        out.append(MyTrade(
            id=t.id, symbol=symbol, price=f"{t.price.normalize():f}", quantity=f"{t.quantity.normalize():f}",
            side=user_side.value, role="taker" if is_taker else "maker", created_at=t.created_at.isoformat(),
        ))
    return out


class ListRequest(BaseModel):
    symbol: str


@router.post("/list", status_code=status.HTTP_201_CREATED)
async def list_market(
    body: ListRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """List a Binance USDT pair for trading as a synthetic market, then seed it with liquidity.

    Lets any user make a view-only pair tradeable. The base asset is internal (settlement in USDT,
    not withdrawable). Idempotent — listing an existing market just re-seeds it.
    """
    try:
        market = await listing.ensure_market(db, body.symbol)
    except ListingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # Quote the new market around the live price so it can be traded immediately.
    reference = await marketmaker.fetch_reference_price(market.symbol)
    if reference is not None:
        await marketmaker.fund_market_maker(db)
        await marketmaker.refresh_market(db, market, reference)
    await db.commit()
    return {"symbol": market.symbol, "status": "listed"}


@router.post("/dev/market-maker/refresh")
async def refresh_market_maker(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Fund the market maker and re-quote every market around the live Binance price. Dev only.

    This is what a background task does continuously in a real deployment; exposing it lets the UI
    seed liquidity on demand.
    """
    _dev_only()
    result = await marketmaker.refresh_all(db)
    for sym in result:
        pubsub.publish(pubsub.market_channel(sym))
    return result


@router.post("/dev/check-triggers")
async def check_triggers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[int]]:
    """Run one stop-order sweep against live prices and fire what has crossed. Dev only.

    The background monitor does this continuously; this lets a test drive it on demand.
    """
    _dev_only()
    fired = await trading.sweep_triggers(db, marketmaker.fetch_reference_price)
    await db.commit()
    for sym in fired:
        pubsub.publish(pubsub.market_channel(sym))
    return fired
