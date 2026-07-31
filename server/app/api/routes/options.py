"""Options endpoints: chain (strikes/expiries), premium quote, buy, positions."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import OptionType, User
from app.services import kyc, marketmaker, options
from app.services.kyc import KycRequired
from app.services.options import OptionError

router = APIRouter(prefix="/options", tags=["options"])
mark_of = marketmaker.fetch_reference_price


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


def _dec(v: str, f: str) -> Decimal:
    try:
        return Decimal(v)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad number in {f}") from None


def _expiries(now: datetime) -> list[datetime]:
    """A few standard expiries: +1d, +7d, +30d at 08:00 UTC."""
    base = now.replace(hour=8, minute=0, second=0, microsecond=0)
    return [base + timedelta(days=d) for d in (1, 7, 30)]


def _strikes(spot: Decimal) -> list[Decimal]:
    """Round strikes bracketing spot, at ±0/±5/±10/±15%."""
    step = _round_step(spot)
    atm = (spot / step).quantize(Decimal(1)) * step
    return [atm + step * i for i in range(-3, 4)]


def _round_step(spot: Decimal) -> Decimal:
    if spot >= 10000:
        return Decimal("1000")
    if spot >= 1000:
        return Decimal("100")
    if spot >= 100:
        return Decimal("10")
    if spot >= 1:
        return Decimal("1")
    return Decimal("0.01")


class Chain(BaseModel):
    underlying: str
    spot: str
    expiries: list[str]
    strikes: list[str]


@router.get("/chain", response_model=Chain)
async def chain(underlying: str = Query("BTC"), db: AsyncSession = Depends(get_db)):
    spot = await mark_of(f"{underlying.upper()}USDT")
    if spot is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"no price for {underlying}")
    now = datetime.now(timezone.utc)
    return Chain(underlying=underlying.upper(), spot=_n(spot),
                 expiries=[e.isoformat() for e in _expiries(now)], strikes=[_n(s) for s in _strikes(spot)])


class QuoteRequest(BaseModel):
    underlying: str
    type: OptionType
    strike: str
    expiry: str
    size: str


@router.post("/quote")
async def quote(body: QuoteRequest):
    try:
        per_unit = await options.quote_premium(
            body.underlying, _dec(body.strike, "strike"), datetime.fromisoformat(body.expiry),
            body.type is OptionType.CALL, now=datetime.now(timezone.utc), price_of=mark_of,
        )
    except OptionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    size = _dec(body.size, "size")
    return {"premium_per_unit": _n(per_unit), "total_premium": _n(per_unit * size)}


class BuyRequest(QuoteRequest):
    pass


@router.post("/buy", status_code=status.HTTP_201_CREATED)
async def buy(body: BuyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await kyc.assert_approved(db, user.id)
    except KycRequired as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    try:
        pos = await options.buy(
            db, user_id=user.id, underlying=body.underlying, type_=body.type, strike=_dec(body.strike, "strike"),
            size=_dec(body.size, "size"), expiry=datetime.fromisoformat(body.expiry),
            now=datetime.now(timezone.utc), price_of=mark_of,
        )
    except OptionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"id": pos.id, "premium_paid": _n(pos.premium_paid), "expiry": pos.expiry.isoformat()}


class PositionRow(BaseModel):
    id: int
    underlying: str
    type: str
    strike: str
    size: str
    premium_paid: str
    expiry: str
    status: str
    payout: str
    mark: str | None


@router.get("/positions", response_model=list[PositionRow])
async def positions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows: list[PositionRow] = []
    for p in await options.open_positions(db, user.id):
        mark = await mark_of(f"{p.underlying}USDT") if p.status.value == "OPEN" else None
        rows.append(PositionRow(
            id=p.id, underlying=p.underlying, type=p.type.value, strike=_n(p.strike), size=_n(p.size),
            premium_paid=_n(p.premium_paid), expiry=p.expiry.isoformat(), status=p.status.value,
            payout=_n(p.payout), mark=_n(mark) if mark else None,
        ))
    return rows
