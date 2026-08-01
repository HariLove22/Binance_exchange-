"""Perpetual futures service: collateral, open/close positions, PnL. USDT-M, cash-settled.

Stage 1 fills at the mark price against the house (insurance) pool — no order book yet. Margin is
locked in the FUTURES wallet on open and released with PnL on close. Mark price is injected so this
module stays offline in tests.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountType,
    Asset,
    FuturesPosition,
    PositionSide,
    PositionStatus,
    WALLET_FUTURES,
    WALLET_SPOT,
)
from app.services import ledger, marketmaker
from app.services.ledger import InsufficientFunds, LedgerError, Movement, TransactionKind

PriceOf = Callable[[str], Awaitable[Decimal | None]]

# --- mark price -----------------------------------------------------------------------------------
# The LAST price is the raw index/reference (what you enter and exit at). The MARK price is a smoothed
# EMA of it, and it — not the last price — drives unrealized PnL and liquidation. Smoothing is the
# whole point: a single manipulated wick moves the last price but barely the mark, so it can't trigger
# a liquidation. ponytail: EMA stands in for Binance's index+basis mark; good enough without a perp
# order book to derive a premium from.
MARK_ALPHA = Decimal("0.3")  # weight on the newest sample; lower = smoother/laggier
_mark_ema: dict[str, Decimal] = {}


async def last_price(symbol: str) -> Decimal | None:
    """The raw reference (index) price — the tradeable last price."""
    return await marketmaker.fetch_reference_price(symbol.upper())


async def mark_price(symbol: str) -> Decimal | None:
    """Smoothed mark price (EMA of the last price). Used for PnL and liquidation, never for fills."""
    s = symbol.upper()
    last = await marketmaker.fetch_reference_price(s)
    if last is None:
        return _mark_ema.get(s)
    prev = _mark_ema.get(s)
    ema = last if prev is None else (MARK_ALPHA * last + (Decimal(1) - MARK_ALPHA) * prev)
    _mark_ema[s] = ema
    return ema

QUOTE = "USDT"                       # margin/settlement asset
MAX_LEVERAGE = Decimal("100")
TAKER_FEE = Decimal("0.0004")        # 0.04%, Binance-ish futures taker fee
MAINTENANCE_MARGIN_RATE = Decimal("0.005")  # 0.5% — liquidate when equity falls below this

# Perpetual funding: every interval, longs pay shorts a fraction of notional (or the reverse if the
# rate were negative). We fill at the index price, so there's no perp/index premium to derive a live
# rate from — a flat positive rate stands in. ponytail: fixed rate; derive from long/short open-
# interest imbalance or a premium index when realism matters.
FUNDING_INTERVAL = timedelta(hours=8)
FUNDING_RATE = Decimal("0.0001")     # 0.01% per 8h, Binance's default baseline


def liquidation_price(pos) -> Decimal:
    """Price at which the position's equity hits maintenance margin and it gets liquidated."""
    mmr = MAINTENANCE_MARGIN_RATE
    if pos.inverse:
        if pos.side is PositionSide.LONG:
            return pos.size * (1 + mmr) / (pos.margin + pos.size / pos.entry_price)
        denom = pos.size / pos.entry_price - pos.margin
        return pos.size * (1 - mmr) / denom if denom > 0 else Decimal(0)
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


async def _asset(db: AsyncSession, symbol: str) -> Asset:
    a = (await db.execute(select(Asset).where(Asset.symbol == symbol))).scalar_one_or_none()
    if a is None:
        raise FuturesError(f"{symbol} is not listed")
    return a


async def _quote_asset(db: AsyncSession) -> Asset:
    return await _asset(db, QUOTE)


def _base_coin(symbol: str) -> str:
    """Strip the quote suffix off a symbol: BTCUSDT/BTCUSD -> BTC."""
    s = symbol.upper()
    for q in ("USDT", "USDC", "USD"):
        if s.endswith(q) and len(s) > len(q):
            return s[: -len(q)]
    return s


async def transfer_collateral(
    db: AsyncSession, *, user_id: int, amount: Decimal, deposit: bool, asset: str = QUOTE,
) -> None:
    """Move margin (USDT for USDT-M, or a coin for COIN-M) between the spot and futures wallets."""
    if amount <= 0:
        raise FuturesError("amount must be positive")
    coll = await _asset(db, asset.upper())
    src, dst = (WALLET_SPOT, WALLET_FUTURES) if deposit else (WALLET_FUTURES, WALLET_SPOT)
    try:
        await ledger.transfer_wallet(
            db, user_id=user_id, asset_id=coll.id, amount=amount, from_wallet=src, to_wallet=dst,
            idempotency_key=f"fut-xfer:{user_id}:{coll.symbol}:{'in' if deposit else 'out'}:{amount}",
            reference="futures-collateral",
        )
    except InsufficientFunds as exc:
        raise FuturesError(str(exc)) from exc


def _notional_at(size: Decimal, price: Decimal, inverse: bool) -> Decimal:
    """Notional in the margin asset: USD for linear (size*price), coin for inverse (size/price)."""
    return size / price if inverse else size * price


async def _new_position(
    db: AsyncSession, *, user_id: int, symbol: str, side: PositionSide, size: Decimal,
    leverage: Decimal, fill: Decimal, inverse: bool,
) -> FuturesPosition:
    """Create a fresh position, locking margin = notional / leverage in the futures wallet."""
    margin_asset = await (_asset(db, _base_coin(symbol)) if inverse else _quote_asset(db))
    margin = _notional_at(size, fill, inverse) / leverage
    try:
        await ledger.lock(
            db, user_id=user_id, asset_id=margin_asset.id, amount=margin, wallet=WALLET_FUTURES,
            idempotency_key=f"fut-open:{user_id}:{symbol}:{side.value}:{size}:{fill}",
            reference=f"futures-open {symbol}",
        )
    except (InsufficientFunds, LedgerError) as exc:
        raise FuturesError(str(exc)) from exc
    pos = FuturesPosition(
        user_id=user_id, symbol=symbol.upper(), side=side, inverse=inverse,
        margin_asset=margin_asset.symbol, size=size, entry_price=fill,
        leverage=leverage, margin=margin, status=PositionStatus.OPEN, realized_pnl=Decimal(0),
    )
    db.add(pos)
    await db.flush()
    return pos


async def open_position(
    db: AsyncSession, *, user_id: int, symbol: str, side: PositionSide, size: Decimal,
    leverage: Decimal, price_of: PriceOf, inverse: bool = False,
) -> FuturesPosition:
    """Open (or net into) a position at the current fill price. One-way netting per (user, symbol,
    contract): same side adds and averages the entry; the opposite side reduces the position, or
    flips it (closing the old and opening the remainder) when the new order is larger.

    Linear (USDT-M): size = base qty, margin in USDT. Inverse (COIN-M): size = USD notional,
    margin in the base coin.
    """
    if size <= 0:
        raise FuturesError("size must be positive")
    if leverage < 1 or leverage > MAX_LEVERAGE:
        raise FuturesError(f"leverage must be between 1x and {MAX_LEVERAGE}x")

    fill = await price_of(symbol)
    if fill is None or fill <= 0:
        raise FuturesError(f"no mark price for {symbol}")

    # ponytail: no row lock — netting is app-level and the demo is single-threaded. Add a partial
    # unique index on (user, symbol, inverse) WHERE status='OPEN' + SELECT FOR UPDATE if real
    # concurrency ever races two orders into two positions.
    existing = (await db.execute(
        select(FuturesPosition).where(
            FuturesPosition.user_id == user_id, FuturesPosition.symbol == symbol.upper(),
            FuturesPosition.inverse == inverse, FuturesPosition.status == PositionStatus.OPEN,
        )
    )).scalar_one_or_none()

    if existing is None:
        return await _new_position(db, user_id=user_id, symbol=symbol, side=side, size=size,
                                   leverage=leverage, fill=fill, inverse=inverse)

    if existing.side is side:
        # Add and average the entry, at the position's existing leverage.
        added_margin = _notional_at(size, fill, inverse) / existing.leverage
        try:
            asset = await _asset(db, existing.margin_asset)
            await ledger.lock(db, user_id=user_id, asset_id=asset.id, amount=added_margin, wallet=WALLET_FUTURES,
                              idempotency_key=f"fut-add:{existing.id}:{size}:{fill}", reference=f"futures-add {symbol}")
        except (InsufficientFunds, LedgerError) as exc:
            raise FuturesError(str(exc)) from exc
        s1, s2 = existing.size, size
        if inverse:
            existing.entry_price = (s1 + s2) / (s1 / existing.entry_price + s2 / fill)
        else:
            existing.entry_price = (s1 * existing.entry_price + s2 * fill) / (s1 + s2)
        existing.size = s1 + s2
        existing.margin += added_margin
        return existing

    # Opposite side: reduce the existing position by the overlap (realising PnL at the fill price).
    overlap = min(existing.size, size)
    await close_position(db, user_id=user_id, position_id=existing.id, price_of=price_of, size=overlap)
    remainder = size - overlap
    if remainder > 0:
        # New order was larger — the position flipped; open the leftover on the new side.
        return await _new_position(db, user_id=user_id, symbol=symbol, side=side, size=remainder,
                                   leverage=leverage, fill=fill, inverse=inverse)
    return existing


async def close_position(
    db: AsyncSession, *, user_id: int, position_id: int, price_of: PriceOf,
    size: Decimal | None = None, liquidation: bool = False,
) -> FuturesPosition:
    """Close a position (or `size` of it) at the mark price: realize PnL, take the fee, release margin.

    `size` None or >= the position size → full close. A partial close settles that fraction of the
    PnL/fee/margin and leaves the rest open with proportionally reduced size and margin.
    """
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

    if size is not None and size <= 0:
        raise FuturesError("close size must be positive")
    partial = size is not None and size < pos.size
    frac = (size / pos.size) if partial else Decimal(1)

    # Quantize to the money scale (18dp) so inverse division dust can't unbalance the ledger.
    q = Decimal(1).scaleb(-18)
    pnl = (pos.pnl_at(mark) * frac).quantize(q)
    fee = (pos.notional(mark) * TAKER_FEE * frac).quantize(q)
    close_margin = (pos.margin * frac).quantize(q) if partial else pos.margin
    margin_asset = await _asset(db, pos.margin_asset)
    await ledger.futures_close(
        db, user_id=user_id, asset_id=margin_asset.id, margin=close_margin, pnl=pnl, fee=fee, wallet=WALLET_FUTURES,
        idempotency_key=f"fut-close:{pos.id}:{mark}:{size or 'full'}",
        reference=f"futures-close {pos.symbol}",
    )
    pos.realized_pnl += pnl - fee
    if partial:
        pos.size -= size
        pos.margin -= close_margin
        return pos

    pos.status = PositionStatus.LIQUIDATED if liquidation else PositionStatus.CLOSED
    pos.close_price = mark
    from sqlalchemy import func as _f
    pos.closed_at = (await db.execute(select(_f.now()))).scalar()
    return pos


async def adjust_margin(
    db: AsyncSession, *, user_id: int, position_id: int, amount: Decimal, add: bool, price_of: PriceOf,
) -> FuturesPosition:
    """Add margin (futures AVAILABLE → this position) or remove it (→ AVAILABLE). Isolated margin, so
    it changes only this position's liquidation price. Removal is refused if it would leave the
    position at/under its maintenance margin at the current mark."""
    if amount <= 0:
        raise FuturesError("amount must be positive")
    pos = (
        await db.execute(select(FuturesPosition).where(FuturesPosition.id == position_id).with_for_update())
    ).scalar_one_or_none()
    if pos is None or pos.user_id != user_id or pos.status is not PositionStatus.OPEN:
        raise FuturesError("position not found")
    asset = await _asset(db, pos.margin_asset)

    if add:
        try:
            await ledger.lock(db, user_id=user_id, asset_id=asset.id, amount=amount, wallet=WALLET_FUTURES,
                              idempotency_key=f"fut-margin-add:{pos.id}:{amount}", reference=f"add margin {pos.symbol}")
        except (InsufficientFunds, LedgerError) as exc:
            raise FuturesError(str(exc)) from exc
        pos.margin += amount
        return pos

    # Remove: would it survive at the current mark? Simulate before moving funds.
    if amount >= pos.margin:
        raise FuturesError("cannot remove the whole margin — close the position instead")
    mark = await price_of(pos.symbol)
    if mark is not None and mark > 0:
        pos.margin -= amount
        underwater = should_liquidate(pos, mark)
        pos.margin += amount
        if underwater:
            raise FuturesError("removing that much margin would liquidate the position")
    await ledger.unlock(db, user_id=user_id, asset_id=asset.id, amount=amount, wallet=WALLET_FUTURES,
                        idempotency_key=f"fut-margin-remove:{pos.id}:{amount}", reference=f"remove margin {pos.symbol}")
    pos.margin -= amount
    return pos


async def set_leverage(
    db: AsyncSession, *, user_id: int, position_id: int, leverage: Decimal, price_of: PriceOf,
) -> FuturesPosition:
    """Change an open position's leverage. Required margin = entry notional / leverage; the difference
    is locked from (lower leverage) or released to (higher leverage) futures AVAILABLE."""
    if leverage < 1 or leverage > MAX_LEVERAGE:
        raise FuturesError(f"leverage must be between 1x and {MAX_LEVERAGE}x")
    pos = (
        await db.execute(select(FuturesPosition).where(FuturesPosition.id == position_id).with_for_update())
    ).scalar_one_or_none()
    if pos is None or pos.user_id != user_id or pos.status is not PositionStatus.OPEN:
        raise FuturesError("position not found")

    asset = await _asset(db, pos.margin_asset)
    q = Decimal(1).scaleb(-18)
    entry_notional = (pos.size / pos.entry_price) if pos.inverse else (pos.size * pos.entry_price)
    required = (entry_notional / leverage).quantize(q)
    delta = required - pos.margin
    try:
        if delta > 0:   # lower leverage → post more margin
            await ledger.lock(db, user_id=user_id, asset_id=asset.id, amount=delta, wallet=WALLET_FUTURES,
                              idempotency_key=f"fut-lev:{pos.id}:{leverage}", reference=f"leverage {pos.symbol}")
        elif delta < 0:  # higher leverage → free margin, but not into liquidation
            mark = await price_of(pos.symbol)
            if mark is not None and mark > 0:
                pos.margin = required
                underwater = should_liquidate(pos, mark)
                pos.margin = required - delta  # restore
                if underwater:
                    raise FuturesError("that leverage would liquidate the position")
            await ledger.unlock(db, user_id=user_id, asset_id=asset.id, amount=-delta, wallet=WALLET_FUTURES,
                                idempotency_key=f"fut-lev:{pos.id}:{leverage}", reference=f"leverage {pos.symbol}")
    except (InsufficientFunds, LedgerError) as exc:
        raise FuturesError(str(exc)) from exc
    pos.leverage = leverage
    pos.margin = required
    return pos


async def open_positions(db: AsyncSession, user_id: int) -> list[FuturesPosition]:
    return list((await db.execute(
        select(FuturesPosition).where(
            FuturesPosition.user_id == user_id, FuturesPosition.status == PositionStatus.OPEN
        ).order_by(FuturesPosition.id.desc())
    )).scalars().all())


async def apply_funding(db: AsyncSession, *, now: datetime, price_of: PriceOf) -> int:
    """Charge one funding interval to every open position that's due. Longs pay the insurance pool,
    shorts receive from it (for a positive rate); it settles against the position's margin. Returns
    how many positions were funded. Caller commits.

    Idempotent per interval: the transaction key is keyed to the interval boundary, and last_funding_at
    advances exactly one interval per charge, so a monitor that fires often can't double-charge.
    """
    due = (await db.execute(
        select(FuturesPosition).where(
            FuturesPosition.status == PositionStatus.OPEN,
            FuturesPosition.last_funding_at <= now - FUNDING_INTERVAL,
        ).with_for_update()
    )).scalars().all()

    q = Decimal(1).scaleb(-18)
    funded = 0
    for pos in due:
        mark = await price_of(pos.symbol)
        if mark is None or mark <= 0:
            continue
        funding = (pos.notional(mark) * FUNDING_RATE).quantize(q)
        interval_key = pos.last_funding_at.isoformat()
        if funding > 0:
            asset = await _asset(db, pos.margin_asset)
            locked = await ledger.get_or_create_account(db, asset.id, AccountType.LOCKED, pos.user_id, wallet=WALLET_FUTURES)
            insurance = await ledger.get_or_create_account(db, asset.id, AccountType.FUTURES_INSURANCE)
            pays = pos.side is PositionSide.LONG  # positive rate → longs pay
            movements = (
                [Movement(locked, -funding), Movement(insurance, funding)] if pays
                else [Movement(insurance, -funding), Movement(locked, funding)]
            )
            await ledger.post(
                db, idempotency_key=f"fut-funding:{pos.id}:{interval_key}", kind=TransactionKind.TRADE,
                reference=f"funding {pos.symbol}", movements=movements,
            )
            signed = -funding if pays else funding
            pos.margin += signed
            pos.funding_accrued += signed
        pos.last_funding_at = pos.last_funding_at + FUNDING_INTERVAL
        funded += 1
    return funded


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
