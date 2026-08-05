"""Perpetual futures service: collateral, open/close positions, PnL. USDT-M, cash-settled.

Stage 1 fills at the mark price against the house (insurance) pool — no order book yet. Margin is
locked in the FUTURES wallet on open and released with PnL on close. Mark price is injected so this
module stays offline in tests.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountType,
    Asset,
    FuturesOrder,
    FuturesOrderStatus,
    FuturesOrderType,
    FuturesPosition,
    Market,
    OPEN_STATUSES,
    Order as SpotOrder,
    OrderSide,
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


async def market_fill_price(db: AsyncSession, *, symbol: str, side: PositionSide, base_qty: Decimal) -> Decimal | None:
    """VWAP a taker of `base_qty` base units pays walking the live order book: a LONG lifts asks
    (lowest first), a SHORT hits bids (highest first). Returns None if the resting depth can't cover
    the whole size — the caller then falls back to the last price.

    This is a price *oracle*: it reads the book's depth so a bigger order gets a worse (slipped)
    fill, but it does not consume it — a futures fill delivers no coin, so the spot book is untouched.
    That's Track B phase 1; a real futures CLOB that consumes its own book is phase 2.
    """
    if base_qty <= 0:
        return None
    market = (await db.execute(select(Market).where(Market.symbol == symbol.upper()))).scalar_one_or_none()
    if market is None:
        return None
    book_side = OrderSide.SELL if side is PositionSide.LONG else OrderSide.BUY
    price_order = SpotOrder.price.asc() if side is PositionSide.LONG else SpotOrder.price.desc()
    remaining = SpotOrder.quantity - SpotOrder.filled_quantity
    rows = (await db.execute(
        select(SpotOrder.price, remaining)
        .where(SpotOrder.market_id == market.id, SpotOrder.side == book_side,
               SpotOrder.status.in_(OPEN_STATUSES))
        .order_by(price_order, SpotOrder.created_at.asc())
    )).all()
    need, cost = base_qty, Decimal(0)
    for price, rem in rows:
        if need <= 0:
            break
        take = min(need, Decimal(rem))
        cost += take * price
        need -= take
    if need > 0:  # book too thin to fill the whole size
        return None
    return cost / base_qty


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
    leverage: Decimal, fill: Decimal, inverse: bool, cross: bool = False,
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
        user_id=user_id, symbol=symbol.upper(), side=side, inverse=inverse, cross=cross,
        margin_asset=margin_asset.symbol, size=size, entry_price=fill,
        leverage=leverage, margin=margin, status=PositionStatus.OPEN, realized_pnl=Decimal(0),
    )
    db.add(pos)
    await db.flush()
    return pos


async def open_position(
    db: AsyncSession, *, user_id: int, symbol: str, side: PositionSide, size: Decimal,
    leverage: Decimal, price_of: PriceOf, inverse: bool = False, cross: bool = False,
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
                                   leverage=leverage, fill=fill, inverse=inverse, cross=cross)

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
                                   leverage=leverage, fill=fill, inverse=inverse, cross=existing.cross)
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
    """Liquidate positions whose equity has fallen to maintenance margin. Caller commits.

    Isolated positions are checked one by one (own margin, own liq price). Cross positions are checked
    as a bucket per (user, margin asset): the whole futures balance for that asset plus the bucket's
    combined margin and unrealized PnL backs them, so a winner cushions a loser — and when the bucket's
    total equity falls to its total maintenance margin, the whole bucket liquidates together.
    """
    positions = (
        await db.execute(select(FuturesPosition).where(FuturesPosition.status == PositionStatus.OPEN).with_for_update())
    ).scalars().all()
    liquidated: list[int] = []

    # Isolated — independent per position.
    for pos in [p for p in positions if not p.cross]:
        mark = await price_of(pos.symbol)
        if mark is None or mark <= 0:
            continue
        if should_liquidate(pos, mark):
            await close_position(db, user_id=pos.user_id, position_id=pos.id, price_of=price_of, liquidation=True)
            liquidated.append(pos.id)

    # Cross — grouped per (user, margin asset).
    buckets: dict[tuple[int, str], list[FuturesPosition]] = {}
    for pos in [p for p in positions if p.cross]:
        buckets.setdefault((pos.user_id, pos.margin_asset), []).append(pos)
    for (uid, asset_sym), group in buckets.items():
        asset = await _asset(db, asset_sym)
        free = (await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, uid, wallet=WALLET_FUTURES)).balance
        equity, maint, priced = free, Decimal(0), True
        for pos in group:
            mark = await price_of(pos.symbol)
            if mark is None or mark <= 0:
                priced = False
                break
            equity += pos.margin + pos.pnl_at(mark)
            maint += pos.notional(mark) * MAINTENANCE_MARGIN_RATE
        if priced and equity <= maint:
            for pos in group:
                await close_position(db, user_id=uid, position_id=pos.id, price_of=price_of, liquidation=True)
                liquidated.append(pos.id)
    return liquidated


# --- resting orders (limit; stop/TP-SL come in Phase B) ------------------------------------------

async def place_limit_order(
    db: AsyncSession, *, user_id: int, symbol: str, side: PositionSide, size: Decimal,
    leverage: Decimal, price: Decimal, inverse: bool = False, cross: bool = False,
) -> FuturesOrder:
    """Rest a LIMIT order. It fills — opening the position at its price — when the last price reaches
    it: a LONG when price falls to the limit, a SHORT when it rises to it. Margin is locked at fill,
    not at placement."""
    if size <= 0 or price <= 0:
        raise FuturesError("size and price must be positive")
    if leverage < 1 or leverage > MAX_LEVERAGE:
        raise FuturesError(f"leverage must be between 1x and {MAX_LEVERAGE}x")
    order = FuturesOrder(
        user_id=user_id, symbol=symbol.upper(), side=side, order_type=FuturesOrderType.LIMIT,
        size=size, price=price, leverage=leverage, inverse=inverse, cross=cross,
        reduce_only=False, status=FuturesOrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()
    return order


async def place_trigger_order(
    db: AsyncSession, *, user_id: int, symbol: str, side: PositionSide,
    order_type: FuturesOrderType, trigger_price: Decimal, size: Decimal | None = None,
    leverage: Decimal | None = None, reduce_only: bool = False,
    inverse: bool = False, cross: bool = False,
) -> FuturesOrder:
    """Rest a STOP_MARKET or TAKE_PROFIT order. It fires at market when the last price crosses the
    trigger (direction implied by type+side, Binance-style — see `_trigger_hit`). A reduce_only order
    closes the matching open position; otherwise it opens a new one at market. Margin locks at fill,
    not at placement."""
    if order_type not in (FuturesOrderType.STOP_MARKET, FuturesOrderType.TAKE_PROFIT):
        raise FuturesError("not a trigger order type")
    if trigger_price <= 0:
        raise FuturesError("trigger price must be positive")
    if size is None or size <= 0:
        raise FuturesError("size must be positive")
    # A stop-entry opens a fresh position at market, so it needs a real leverage; a reduce_only
    # trigger just closes the existing one — leverage is irrelevant, store 1x to satisfy the check.
    if not reduce_only and (leverage is None or leverage < 1 or leverage > MAX_LEVERAGE):
        raise FuturesError(f"leverage must be between 1x and {MAX_LEVERAGE}x")
    order = FuturesOrder(
        user_id=user_id, symbol=symbol.upper(), side=side, order_type=order_type,
        size=size, price=trigger_price, leverage=leverage or Decimal(1),
        inverse=inverse, cross=cross, reduce_only=reduce_only, status=FuturesOrderStatus.PENDING,
    )
    db.add(order)
    await db.flush()
    return order


async def cancel_order(db: AsyncSession, *, user_id: int, order_id: int) -> FuturesOrder:
    order = (await db.execute(select(FuturesOrder).where(FuturesOrder.id == order_id))).scalar_one_or_none()
    if order is None or order.user_id != user_id:
        raise FuturesError("order not found")
    if order.status is not FuturesOrderStatus.PENDING:
        raise FuturesError("order is not open")
    order.status = FuturesOrderStatus.CANCELLED
    await db.flush()
    return order


async def open_orders(db: AsyncSession, user_id: int) -> list[FuturesOrder]:
    return list((await db.execute(
        select(FuturesOrder).where(
            FuturesOrder.user_id == user_id, FuturesOrder.status == FuturesOrderStatus.PENDING
        ).order_by(FuturesOrder.id.desc())
    )).scalars().all())


def _limit_crossed(side: PositionSide, last: Decimal, price: Decimal) -> bool:
    """A buy (LONG) fills when the price falls to the limit; a sell (SHORT) when it rises to it."""
    return last <= price if side is PositionSide.LONG else last >= price


def _trigger_hit(order_type: FuturesOrderType, side: PositionSide, last: Decimal, trigger: Decimal) -> bool:
    """When a STOP/TP trigger fires, Binance-style. A stop-buy or take-profit-sell sits above the
    market and fires as the price rises to it; a stop-sell or take-profit-buy sits below and fires as
    it falls. (LONG ≡ buy, SHORT ≡ sell — matching the position/close direction.)"""
    above = ((order_type is FuturesOrderType.STOP_MARKET and side is PositionSide.LONG)
             or (order_type is FuturesOrderType.TAKE_PROFIT and side is PositionSide.SHORT))
    return last >= trigger if above else last <= trigger


async def _find_open_position(db: AsyncSession, user_id: int, symbol: str, inverse: bool) -> FuturesPosition | None:
    return (await db.execute(
        select(FuturesPosition).where(
            FuturesPosition.user_id == user_id, FuturesPosition.symbol == symbol.upper(),
            FuturesPosition.inverse == inverse, FuturesPosition.status == PositionStatus.OPEN,
        )
    )).scalar_one_or_none()


async def sweep_orders(db: AsyncSession, price_of: PriceOf) -> list[int]:
    """Fill every resting order the price has reached. LIMIT opens at the order's price; STOP_MARKET
    and TAKE_PROFIT fire at market when their trigger is crossed — a reduce_only trigger closes the
    matching open position, otherwise it opens a new one. Caller commits. A fill that fails (e.g. not
    enough margin yet) is left PENDING to retry.

    ponytail: triggers key off the last price, same feed as LIMIT — fine for our own market feed.
    Switch to the mark price here if wick manipulation ever becomes a concern.
    """
    orders = (await db.execute(
        select(FuturesOrder).where(FuturesOrder.status == FuturesOrderStatus.PENDING)
    )).scalars().all()
    filled: list[int] = []
    for o in orders:
        last = await price_of(o.symbol)
        if last is None or last <= 0:
            continue

        try:
            if o.order_type is FuturesOrderType.LIMIT:
                if not _limit_crossed(o.side, last, o.price):
                    continue

                async def _at(_sym: str, _p: Decimal = o.price) -> Decimal:
                    return _p  # fill at the limit price

                await open_position(db, user_id=o.user_id, symbol=o.symbol, side=o.side, size=o.size,
                                    leverage=o.leverage, price_of=_at, inverse=o.inverse, cross=o.cross)
            else:  # STOP_MARKET / TAKE_PROFIT — fire at market when the trigger is crossed
                if not _trigger_hit(o.order_type, o.side, last, o.price):
                    continue
                if o.reduce_only:
                    pos = await _find_open_position(db, o.user_id, o.symbol, o.inverse)
                    if pos is None:  # position already gone — this TP/SL is orphaned
                        o.status = FuturesOrderStatus.CANCELLED
                        continue
                    await close_position(db, user_id=o.user_id, position_id=pos.id, price_of=price_of)
                else:
                    await open_position(db, user_id=o.user_id, symbol=o.symbol, side=o.side, size=o.size,
                                        leverage=o.leverage, price_of=price_of, inverse=o.inverse, cross=o.cross)
        except FuturesError:
            continue  # leave PENDING — retries next sweep once fundable

        o.status = FuturesOrderStatus.FILLED
        o.filled_at = datetime.now(timezone.utc)
        filled.append(o.id)
    return filled
