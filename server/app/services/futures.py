"""Futures: open/close leveraged LONG/SHORT positions, settled against the mark price.

Margin = notional / leverage is locked in the FUTURES sub-wallet on open (moved from spot, so a
position never risks more spot funds than its margin). PnL settles against the FUTURES_POOL house
account on close — a win is paid from it, a loss swept into it — so the books stay balanced. A
liquidation is just a close forced when equity falls to the maintenance margin.

The mark price is passed in (from the live reference feed at the route layer), so this module is
pure and deterministic to test. `open`/`close` are the only writers; PnL and liquidation price are
pure functions reused by the display and the liquidation monitor.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountType,
    FuturesPosition,
    Market,
    PositionSide,
    PositionStatus,
    WALLET_FUTURES,
    WALLET_SPOT,
)
from app.services import ledger
from app.services.ledger import Movement, TransactionKind

MAX_LEVERAGE = Decimal("20")
# Maintenance margin rate: liquidate once equity falls to this fraction of the position's value.
MMR = Decimal("0.005")  # 0.5%


class FuturesError(Exception):
    pass


def _sign(side: PositionSide) -> Decimal:
    return Decimal(1) if side is PositionSide.LONG else Decimal(-1)


def unrealized_pnl(side: PositionSide, entry_price: Decimal, mark_price: Decimal, size: Decimal) -> Decimal:
    """(mark - entry) * size for LONG; the inverse for SHORT."""
    return (mark_price - entry_price) * size * _sign(side)


def liquidation_price(side: PositionSide, entry_price: Decimal, leverage: Decimal, mmr: Decimal = MMR) -> Decimal:
    """The price at which equity (margin + uPnL) falls to the maintenance margin.

    LONG:  entry * (1 - 1/lev + mmr)   — drops below entry
    SHORT: entry * (1 + 1/lev - mmr)   — rises above entry
    """
    inv = Decimal(1) / leverage
    if side is PositionSide.LONG:
        return entry_price * (Decimal(1) - inv + mmr)
    return entry_price * (Decimal(1) + inv - mmr)


async def _market(db: AsyncSession, symbol: str) -> Market:
    m = (await db.execute(select(Market).where(Market.symbol == symbol.upper()))).scalar_one_or_none()
    if m is None:
        raise FuturesError(f"unknown market {symbol!r}")
    return m


async def open_position(
    db: AsyncSession,
    *,
    user_id: int,
    symbol: str,
    side: PositionSide,
    leverage: Decimal,
    quantity: Decimal,
    mark_price: Decimal,
) -> FuturesPosition:
    """Open a position at the mark price, locking margin from spot into the futures wallet."""
    if leverage < 1 or leverage > MAX_LEVERAGE:
        raise FuturesError(f"leverage must be between 1x and {MAX_LEVERAGE}x")
    if quantity <= 0 or mark_price <= 0:
        raise FuturesError("quantity and price must be positive")

    market = await _market(db, symbol)
    entry = mark_price
    margin = entry * quantity / leverage
    liq = liquidation_price(side, entry, leverage)

    # Lock margin: spot AVAILABLE -> futures LOCKED, one balanced move in the quote asset.
    q = market.quote_asset_id
    spot = await ledger.get_or_create_account(db, q, AccountType.AVAILABLE, user_id, wallet=WALLET_SPOT)
    locked = await ledger.get_or_create_account(db, q, AccountType.LOCKED, user_id, wallet=WALLET_FUTURES)
    if spot.balance < margin:
        raise FuturesError(f"insufficient margin: need {margin}, have {spot.balance}")

    await ledger.post(
        db,
        idempotency_key=f"fut-open:{user_id}:{market.symbol}:{uuid.uuid4()}",
        kind=TransactionKind.ORDER_LOCK,
        reference=f"futures-open {market.symbol}",
        movements=[Movement(spot, -margin), Movement(locked, margin)],
    )

    pos = FuturesPosition(
        user_id=user_id, symbol=market.symbol, side=side, leverage=leverage,
        size=quantity, entry_price=entry, margin=margin, liquidation_price=liq,
        realized_pnl=Decimal(0), status=PositionStatus.OPEN,
    )
    db.add(pos)
    await db.flush()
    return pos


async def close_position(db: AsyncSession, *, position: FuturesPosition, mark_price: Decimal) -> Decimal:
    """Close at the mark price: release margin, settle PnL against the pool. Returns realized PnL."""
    if position.status is not PositionStatus.OPEN:
        raise FuturesError("position is not open")

    market = await _market(db, position.symbol)
    q = market.quote_asset_id
    pnl = unrealized_pnl(position.side, position.entry_price, mark_price, position.size)
    # A loss can never exceed the posted margin — liquidation guarantees it. Clamp so a close a hair
    # past the liquidation line still can't drive the user's balance negative.
    if pnl < -position.margin:
        pnl = -position.margin
    payout = position.margin + pnl  # what returns to spot AVAILABLE

    locked = await ledger.get_or_create_account(db, q, AccountType.LOCKED, position.user_id, wallet=WALLET_FUTURES)
    spot = await ledger.get_or_create_account(db, q, AccountType.AVAILABLE, position.user_id, wallet=WALLET_SPOT)
    pool = await ledger.get_or_create_account(db, q, AccountType.FUTURES_POOL, wallet=WALLET_FUTURES)

    # -margin (release) + payout (to spot) + (-pnl) (pool) = 0. Zero legs dropped: post() rejects them.
    movements = [Movement(locked, -position.margin)]
    if payout != 0:
        movements.append(Movement(spot, payout))
    if pnl != 0:
        movements.append(Movement(pool, -pnl))

    await ledger.post(
        db,
        idempotency_key=f"fut-close:{position.id}",
        kind=TransactionKind.ORDER_UNLOCK,
        reference=f"futures-close {position.symbol}",
        movements=movements,
    )

    position.status = PositionStatus.CLOSED
    position.realized_pnl = pnl
    position.closed_at = datetime.now(timezone.utc)
    await db.flush()
    return pnl


async def liquidate(db: AsyncSession, *, position: FuturesPosition, mark_price: Decimal) -> Decimal:
    """Force-close a position that has hit its maintenance margin."""
    pnl = await close_position(db, position=position, mark_price=mark_price)
    position.status = PositionStatus.LIQUIDATED
    await db.flush()
    return pnl


def _should_liquidate(side: PositionSide, mark: Decimal, liq_price: Decimal) -> bool:
    """A long dies when price falls to its liq price; a short when price rises to it."""
    return mark <= liq_price if side is PositionSide.LONG else mark >= liq_price


async def sweep_liquidations(db: AsyncSession, price_of) -> list[int]:
    """Price every open position against the feed and liquidate whatever has crossed. Returns the ids
    liquidated. Called by the background monitor; the caller owns the commit.

    ponytail: a gap past the liq price closes at the current mark, so a loss beyond margin is absorbed
    by the pool (bad debt). Add insurance-fund accounting if that matters.
    """
    positions = (
        await db.execute(select(FuturesPosition).where(FuturesPosition.status == PositionStatus.OPEN))
    ).scalars().all()
    liquidated: list[int] = []
    marks: dict[str, Decimal | None] = {}
    for pos in positions:
        if pos.symbol not in marks:
            marks[pos.symbol] = await price_of(pos.symbol)
        mark = marks[pos.symbol]
        if mark is not None and _should_liquidate(pos.side, mark, pos.liquidation_price):
            await liquidate(db, position=pos, mark_price=mark)
            liquidated.append(pos.id)
    return liquidated
