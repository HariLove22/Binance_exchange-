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
    Market,
    OPEN_STATUSES,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Trade,
    User,
)
from app.services import marketmaker, trading
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


class OrderResponse(BaseModel):
    id: int
    symbol: str
    side: str
    type: str
    price: str | None
    quantity: str
    filled_quantity: str
    status: str


def _order_response(order: Order, symbol: str) -> OrderResponse:
    return OrderResponse(
        id=order.id, symbol=symbol, side=order.side.value, type=order.type.value,
        price=f"{order.price.normalize():f}" if order.price is not None else None,
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
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad number") from None

    try:
        placed = await trading.place_order(
            db, user_id=user.id, market=market, side=body.side,
            order_type=body.type, quantity=quantity, price=price,
        )
    except TradingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _order_response(placed.order, market.symbol)


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
    return _order_response(order, market.symbol)


@router.get("/orders", response_model=list[OrderResponse])
async def open_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    include_history: bool = Query(False),
):
    q = select(Order, Market.symbol).join(Market, Market.id == Order.market_id).where(Order.user_id == user.id)
    if not include_history:
        q = q.where(Order.status.in_(OPEN_STATUSES))
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
    return await marketmaker.refresh_all(db)
