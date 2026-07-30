"""Futures endpoints: open and close leveraged positions, and list your positions.

Positions settle against the mark price — the live reference price, the same feed spot stops use.
Opening/closing runs in one request and one transaction; on any error nothing moves.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import FuturesPosition, PositionSide, PositionStatus, User
from app.services import futures, marketmaker
from app.services.futures import FuturesError

router = APIRouter(prefix="/futures", tags=["futures"])


class OpenRequest(BaseModel):
    symbol: str
    side: PositionSide
    leverage: str
    quantity: str


class PositionOut(BaseModel):
    id: int
    symbol: str
    side: str
    leverage: str
    size: str
    entry_price: str
    margin: str
    liquidation_price: str
    realized_pnl: str
    status: str
    mark_price: str | None
    unrealized_pnl: str | None
    created_at: str
    closed_at: str | None


def _fmt(v: Decimal) -> str:
    return f"{v.normalize():f}"


def _position_out(pos: FuturesPosition, mark: Decimal | None) -> PositionOut:
    upnl = (
        futures.unrealized_pnl(pos.side, pos.entry_price, mark, pos.size)
        if mark is not None and pos.status is PositionStatus.OPEN
        else None
    )
    return PositionOut(
        id=pos.id, symbol=pos.symbol, side=pos.side.value, leverage=_fmt(pos.leverage),
        size=_fmt(pos.size), entry_price=_fmt(pos.entry_price), margin=_fmt(pos.margin),
        liquidation_price=_fmt(pos.liquidation_price), realized_pnl=_fmt(pos.realized_pnl),
        status=pos.status.value, mark_price=_fmt(mark) if mark is not None else None,
        unrealized_pnl=_fmt(upnl) if upnl is not None else None,
        created_at=pos.created_at.isoformat(), closed_at=pos.closed_at.isoformat() if pos.closed_at else None,
    )


async def _mark(symbol: str) -> Decimal:
    price = await marketmaker.fetch_reference_price(symbol.upper())
    if price is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"no reference price for {symbol}")
    return price


@router.post("/position", response_model=PositionOut, status_code=status.HTTP_201_CREATED)
async def open_position(
    body: OpenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        leverage = Decimal(body.leverage)
        quantity = Decimal(body.quantity)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad number") from None

    mark = await _mark(body.symbol)
    try:
        pos = await futures.open_position(
            db, user_id=user.id, symbol=body.symbol, side=body.side,
            leverage=leverage, quantity=quantity, mark_price=mark,
        )
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _position_out(pos, mark)


@router.post("/position/{position_id}/close", response_model=PositionOut)
async def close_position(
    position_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pos = await db.get(FuturesPosition, position_id)
    if pos is None or pos.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "position not found")

    mark = await _mark(pos.symbol)
    try:
        await futures.close_position(db, position=pos, mark_price=mark)
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _position_out(pos, mark)


@router.get("/positions", response_model=list[PositionOut])
async def list_positions(
    include_closed: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(FuturesPosition).where(FuturesPosition.user_id == user.id)
    if not include_closed:
        q = q.where(FuturesPosition.status == PositionStatus.OPEN)
    positions = list((await db.execute(q.order_by(FuturesPosition.id.desc()))).scalars().all())

    # One reference-price fetch per distinct open symbol, for a live PnL snapshot.
    marks: dict[str, Decimal | None] = {}
    for p in positions:
        if p.status is PositionStatus.OPEN and p.symbol not in marks:
            marks[p.symbol] = await marketmaker.fetch_reference_price(p.symbol)
    return [_position_out(p, marks.get(p.symbol)) for p in positions]
