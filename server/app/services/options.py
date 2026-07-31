"""European options service: Black-Scholes premium, buy, and expiry settlement (cash, USDT).

The house writes every option. Buying pays the premium to the house pool; at expiry an in-the-money
option pays its intrinsic value back from the pool, out-of-the-money expires worthless. Premium uses
Black-Scholes with a fixed implied vol (r = 0) — good enough to price realistically without a vol
surface. ponytail: fixed IV, no Greeks/vol-surface; add them if real MM pricing is needed.
"""

import math
from datetime import datetime
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, OptionPosition, OptionStatus, OptionType
from app.services import ledger
from app.services.ledger import InsufficientFunds

PriceOf = Callable[[str], Awaitable[Decimal | None]]

QUOTE = "USDT"
IV = 0.65                    # fixed annualized implied volatility
SECONDS_PER_YEAR = 365 * 24 * 3600
MIN_PREMIUM_RATE = Decimal("0.001")  # floor: 0.1% of notional, so near-expiry OTM isn't free


class OptionError(Exception):
    """An options action was refused. Safe to surface to a caller."""


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_premium(spot: Decimal, strike: Decimal, years: float, is_call: bool) -> Decimal:
    """Black-Scholes price per unit of underlying (r = 0, fixed IV). Floored to a small time value."""
    S, K = float(spot), float(strike)
    if years <= 0:
        intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
        return Decimal(str(intrinsic))
    vt = IV * math.sqrt(years)
    d1 = (math.log(S / K) + (IV * IV / 2) * years) / vt
    d2 = d1 - vt
    price = S * _norm_cdf(d1) - K * _norm_cdf(d2) if is_call else K * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    floor = float(S * float(MIN_PREMIUM_RATE))
    return Decimal(str(round(max(price, floor), 8)))


async def quote_premium(
    underlying: str, strike: Decimal, expiry: datetime, is_call: bool, *, now: datetime, price_of: PriceOf
) -> Decimal:
    spot = await price_of(f"{underlying.upper()}USDT")
    if spot is None or spot <= 0:
        raise OptionError(f"no price for {underlying}")
    years = max(0.0, (expiry - now).total_seconds() / SECONDS_PER_YEAR)
    return bs_premium(spot, strike, years, is_call)


async def buy(
    db: AsyncSession, *, user_id: int, underlying: str, type_: OptionType, strike: Decimal,
    size: Decimal, expiry: datetime, now: datetime, price_of: PriceOf,
) -> OptionPosition:
    if size <= 0 or strike <= 0:
        raise OptionError("size and strike must be positive")
    if expiry <= now:
        raise OptionError("expiry must be in the future")

    per_unit = await quote_premium(underlying, strike, expiry, type_ is OptionType.CALL, now=now, price_of=price_of)
    premium = per_unit * size
    quote = (await db.execute(select(Asset).where(Asset.symbol == QUOTE))).scalar_one_or_none()
    if quote is None:
        raise OptionError(f"{QUOTE} not listed")

    pos = OptionPosition(
        user_id=user_id, underlying=underlying.upper(), type=type_, strike=strike, size=size,
        premium_paid=premium, expiry=expiry, status=OptionStatus.OPEN,
    )
    db.add(pos)
    await db.flush()
    try:
        await ledger.house_transfer(
            db, user_id=user_id, asset_id=quote.id, amount=premium, to_house=True,
            idempotency_key=f"opt-buy:{pos.id}", reference=f"option-buy {pos.id}",
        )
    except InsufficientFunds as exc:
        raise OptionError(str(exc)) from exc
    return pos


async def open_positions(db: AsyncSession, user_id: int) -> list[OptionPosition]:
    return list((await db.execute(
        select(OptionPosition).where(OptionPosition.user_id == user_id).order_by(OptionPosition.id.desc()).limit(100)
    )).scalars().all())


async def sweep_expiries(db: AsyncSession, *, now: datetime, price_of: PriceOf) -> list[int]:
    """Settle every open option whose expiry has passed, at the mark price. Caller commits."""
    due = (await db.execute(
        select(OptionPosition).where(OptionPosition.status == OptionStatus.OPEN, OptionPosition.expiry <= now)
        .with_for_update()
    )).scalars().all()
    settled: list[int] = []
    quote = (await db.execute(select(Asset).where(Asset.symbol == QUOTE))).scalar_one_or_none()
    for pos in due:
        mark = await price_of(f"{pos.underlying}USDT")
        if mark is None:
            continue
        payout = pos.intrinsic(mark)
        if payout > 0 and quote is not None:
            await ledger.house_transfer(
                db, user_id=pos.user_id, asset_id=quote.id, amount=payout, to_house=False,
                idempotency_key=f"opt-settle:{pos.id}", reference=f"option-settle {pos.id}",
            )
        pos.status = OptionStatus.EXERCISED if payout > 0 else OptionStatus.EXPIRED
        pos.payout = payout
        pos.settle_price = mark
        pos.settled_at = now
        settled.append(pos.id)
    return settled
