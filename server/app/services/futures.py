"""Perpetual futures service: collateral, open/close positions, PnL. USDT-M, cash-settled.

Stage 1 fills at the mark price against the house (insurance) pool — no order book yet. Margin is
locked in the FUTURES wallet on open and released with PnL on close. Mark price is injected so this
module stays offline in tests.
"""

from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Asset,
    FuturesPosition,
    PositionSide,
    PositionStatus,
    WALLET_FUTURES,
    WALLET_SPOT,
)
from app.services import ledger
from app.services.ledger import InsufficientFunds, LedgerError

PriceOf = Callable[[str], Awaitable[Decimal | None]]

QUOTE = "USDT"                       # margin/settlement asset
MAX_LEVERAGE = Decimal("100")
TAKER_FEE = Decimal("0.0004")        # 0.04%, Binance-ish futures taker fee
MAINTENANCE_MARGIN_RATE = Decimal("0.005")  # 0.5% — liquidate when equity falls below this


def liquidation_price(pos) -> Decimal:
    """Price at which the position's equity hits maintenance margin and it gets liquidated."""
    mmr = MAINTENANCE_MARGIN_RATE
    if pos.side is PositionSide.LONG:
        return (pos.entry_price * pos.size - pos.margin) / (pos.size * (1 - mmr))
    return (pos.margin + pos.entry_price * pos.size) / (pos.size * (1 + mmr))


def should_liquidate(pos, mark: Decimal) -> bool:
    equity = pos.margin + pos.pnl_at(mark)
    maintenance = pos.notional(mark) * MAINTENANCE_MARGIN_RATE
    return equity <= maintenance


def position_state(pos, mark: Decimal) -> dict:
    """Live position metrics for display."""
    pnl = pos.pnl_at(mark)
    return {
        "mark": mark,
        "unrealized_pnl": pnl,
        "equity": pos.margin + pnl,
        "roe": (pnl / pos.margin * 100) if pos.margin else Decimal(0),  # return on margin, %
        "liquidation_price": liquidation_price(pos),
    }


class FuturesError(Exception):
    """A futures action was refused. Safe to surface to a caller."""


async def _quote_asset(db: AsyncSession) -> Asset:
    a = (await db.execute(select(Asset).where(Asset.symbol == QUOTE))).scalar_one_or_none()
    if a is None:
        raise FuturesError(f"{QUOTE} is not listed")
    return a


async def transfer_collateral(db: AsyncSession, *, user_id: int, amount: Decimal, deposit: bool) -> None:
    """Move USDT margin between the spot wallet and the futures wallet."""
    if amount <= 0:
        raise FuturesError("amount must be positive")
    quote = await _quote_asset(db)
    src, dst = (WALLET_SPOT, WALLET_FUTURES) if deposit else (WALLET_FUTURES, WALLET_SPOT)
    try:
        await ledger.transfer_wallet(
            db, user_id=user_id, asset_id=quote.id, amount=amount, from_wallet=src, to_wallet=dst,
            idempotency_key=f"fut-xfer:{user_id}:{'in' if deposit else 'out'}:{amount}",
            reference="futures-collateral",
        )
    except InsufficientFunds as exc:
        raise FuturesError(str(exc)) from exc


async def open_position(
    db: AsyncSession, *, user_id: int, symbol: str, side: PositionSide, size: Decimal,
    leverage: Decimal, price_of: PriceOf,
) -> FuturesPosition:
    """Open a leveraged position at the current mark price, locking margin in the futures wallet."""
    if size <= 0:
        raise FuturesError("size must be positive")
    if leverage < 1 or leverage > MAX_LEVERAGE:
        raise FuturesError(f"leverage must be between 1x and {MAX_LEVERAGE}x")

    mark = await price_of(symbol)
    if mark is None or mark <= 0:
        raise FuturesError(f"no mark price for {symbol}")

    quote = await _quote_asset(db)
    notional = size * mark
    margin = notional / leverage
    try:
        await ledger.lock(
            db, user_id=user_id, asset_id=quote.id, amount=margin, wallet=WALLET_FUTURES,
            idempotency_key=f"fut-open:{user_id}:{symbol}:{side.value}:{size}:{mark}",
            reference=f"futures-open {symbol}",
        )
    except (InsufficientFunds, LedgerError) as exc:
        raise FuturesError(str(exc)) from exc

    pos = FuturesPosition(
        user_id=user_id, symbol=symbol.upper(), side=side, size=size, entry_price=mark,
        leverage=leverage, margin=margin, status=PositionStatus.OPEN, realized_pnl=Decimal(0),
    )
    db.add(pos)
    await db.flush()
    return pos


async def close_position(
    db: AsyncSession, *, user_id: int, position_id: int, price_of: PriceOf, liquidation: bool = False
) -> FuturesPosition:
    """Close a position at the mark price: realize PnL, take the fee, release margin."""
    pos = (
        await db.execute(select(FuturesPosition).where(FuturesPosition.id == position_id).with_for_update())
    ).scalar_one_or_none()
    if pos is None or pos.user_id != user_id:
        raise FuturesError("position not found")
    if pos.status is not PositionStatus.OPEN:
        raise FuturesError("position is not open")

    mark = await price_of(pos.symbol)
    if mark is None or mark <= 0:
        raise FuturesError(f"no mark price for {pos.symbol}")

    pnl = pos.pnl_at(mark)
    fee = pos.notional(mark) * TAKER_FEE
    quote = await _quote_asset(db)
    await ledger.futures_close(
        db, user_id=user_id, asset_id=quote.id, margin=pos.margin, pnl=pnl, fee=fee, wallet=WALLET_FUTURES,
        idempotency_key=f"fut-close:{pos.id}:{mark}",
        reference=f"futures-close {pos.symbol}",
    )
    pos.status = PositionStatus.LIQUIDATED if liquidation else PositionStatus.CLOSED
    pos.close_price = mark
    pos.realized_pnl = pnl - fee
    from sqlalchemy import func as _f
    pos.closed_at = (await db.execute(select(_f.now()))).scalar()
    return pos


async def open_positions(db: AsyncSession, user_id: int) -> list[FuturesPosition]:
    return list((await db.execute(
        select(FuturesPosition).where(
            FuturesPosition.user_id == user_id, FuturesPosition.status == PositionStatus.OPEN
        ).order_by(FuturesPosition.id.desc())
    )).scalars().all())


async def sweep_liquidations(db: AsyncSession, price_of: PriceOf) -> list[int]:
    """Liquidate every open position whose equity has fallen to maintenance margin. Caller commits."""
    positions = (
        await db.execute(select(FuturesPosition).where(FuturesPosition.status == PositionStatus.OPEN).with_for_update())
    ).scalars().all()
    liquidated: list[int] = []
    for pos in positions:
        mark = await price_of(pos.symbol)
        if mark is None or mark <= 0:
            continue
        if should_liquidate(pos, mark):
            await close_position(db, user_id=pos.user_id, position_id=pos.id, price_of=price_of, liquidation=True)
            liquidated.append(pos.id)
    return liquidated
