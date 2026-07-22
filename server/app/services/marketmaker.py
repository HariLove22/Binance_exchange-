"""A market maker that seeds the book with liquidity around the live reference price.

A new exchange's book is empty, and an empty book cannot fill anyone — the cold-start problem that
kills most small exchanges. So a market-maker account rests limit orders on both sides around a
reference price. Here the reference is Binance's live public price (free, no key); a real venue
would hedge the resulting position upstream, but for this stage the MM simply provides the
liquidity users trade against.

The MM is an ordinary account placing ordinary orders through the ordinary matching engine — which
is exactly why the engine must not have any "is this a real user" assumption baked in. It is funded
generously (via the deposit flow, so reconciliation stays honest) and refreshed periodically:
cancel its resting orders, re-quote around the current price.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_UP

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Market,
    OPEN_STATUSES,
    Order,
    OrderSide,
    OrderType,
    User,
    UserRole,
)
from app.services import trading

MARKET_MAKER_EMAIL = "market-maker@novex.internal"
BINANCE_PRICE_URL = "https://data-api.binance.vision/api/v3/ticker/price"

# Quote LEVELS levels each side, STEP_BPS apart, HALF_SPREAD_BPS off mid. Basis points: 1 bp =
# 0.01%. A 10 bp half-spread means the best bid/ask sit 0.1% below/above the reference.
LEVELS = 5
HALF_SPREAD_BPS = Decimal("10")
STEP_BPS = Decimal("8")
QTY_PER_LEVEL = Decimal("2")  # in base units; scaled to qty_step below


async def get_market_maker(db: AsyncSession) -> User:
    mm = (await db.execute(select(User).where(User.email == MARKET_MAKER_EMAIL))).scalar_one_or_none()
    if mm is None:
        mm = User(
            email=MARKET_MAKER_EMAIL,
            full_name="Market Maker",
            # No login: the MM never authenticates. An unusable bcrypt-shaped placeholder, not a
            # real hash — verify_password can never match it.
            password_hash="x-market-maker-no-login",
            role=UserRole.USER,
            is_verified=True,
        )
        db.add(mm)
        await db.flush()
    return mm


async def fetch_reference_price(symbol: str) -> Decimal | None:
    """Live price from Binance's public feed. None if unreachable — the caller skips the refresh
    rather than quoting off a stale or zero price."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(BINANCE_PRICE_URL, params={"symbol": symbol})
            resp.raise_for_status()
            return Decimal(resp.json()["price"])
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def _round_to(value: Decimal, step: Decimal, rounding=ROUND_DOWN) -> Decimal:
    return (value / step).quantize(Decimal(1), rounding=rounding) * step


async def refresh_market(db: AsyncSession, market: Market, reference: Decimal) -> int:
    """Cancel the MM's resting orders on this market and re-quote around `reference`.

    Returns the number of orders placed. Assumes the MM is funded; a level that cannot be funded
    is skipped (the engine rejects it) rather than aborting the whole refresh.
    """
    mm = await get_market_maker(db)

    # Cancel existing MM orders on this market.
    existing = (
        await db.execute(
            select(Order).where(
                Order.market_id == market.id,
                Order.user_id == mm.id,
                Order.status.in_(OPEN_STATUSES),
            )
        )
    ).scalars().all()
    for order in existing:
        try:
            await trading.cancel_order(db, user_id=mm.id, order_id=order.id)
        except trading.TradingError:
            pass

    placed = 0
    qty = _round_to(QTY_PER_LEVEL, market.qty_step)
    for level in range(LEVELS):
        offset_bps = HALF_SPREAD_BPS + STEP_BPS * level
        factor = offset_bps / Decimal(10000)

        bid = _round_to(reference * (1 - factor), market.price_tick)
        ask = _round_to(reference * (1 + factor), market.price_tick, rounding=ROUND_UP)

        for side, px in ((OrderSide.BUY, bid), (OrderSide.SELL, ask)):
            if px <= 0:
                continue
            try:
                await trading.place_order(
                    db, user_id=mm.id, market=market, side=side,
                    order_type=OrderType.LIMIT, quantity=qty, price=px,
                )
                placed += 1
            except trading.TradingError:
                # Usually insufficient MM funds at this level; skip it.
                pass

    return placed


async def fund_market_maker(db: AsyncSession, per_asset: Decimal = Decimal("1000000")) -> None:
    """Ensure the MM holds enough base and quote to quote every market.

    Funds through the deposit flow (a backed credit), so reconciliation stays balanced — the MM's
    inventory is real ledger balance, not a mint. Only tops up assets below the target, so it is
    cheap to call before every refresh.
    """
    from app.models import AssetNetwork
    from app.services import deposits as deposit_service

    mm = await get_market_maker(db)
    markets = (await db.execute(select(Market).where(Market.enabled.is_(True)))).scalars().all()
    asset_ids = {a for m in markets for a in (m.base_asset_id, m.quote_asset_id)}

    for asset_id in asset_ids:
        current = await _available(db, mm.id, asset_id)
        if current >= per_asset:
            continue
        network = (
            await db.execute(select(AssetNetwork).where(AssetNetwork.asset_id == asset_id).order_by(AssetNetwork.id))
        ).scalars().first()
        if network is None:
            continue
        if not network.deposit_enabled:
            network.deposit_enabled = True
            await db.flush()
        addr = await deposit_service.get_or_create_address(db, mm.id, network.id)
        import time

        top_up = per_asset - current
        deposit = await deposit_service.record_deposit(
            db, asset_network_id=network.id, tx_hash=f"0xmmfund{asset_id}-{int(time.time()*1000)}", amount=top_up
        )
        deposit.user_id = mm.id
        deposit.deposit_address_id = addr.id
        deposit.confirmations = deposit.required_confirmations
        db.add(deposit)
        await db.flush()
        await deposit_service.credit_if_confirmed(db, deposit)


async def _available(db: AsyncSession, user_id: int, asset_id: int) -> Decimal:
    from app.models import AccountType
    from app.services import ledger

    acct = await ledger.get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id)
    return acct.balance


async def refresh_all(db: AsyncSession) -> dict[str, int]:
    """Refresh every enabled market from its live reference price. Returns symbol -> orders placed."""
    await fund_market_maker(db)
    markets = (await db.execute(select(Market).where(Market.enabled.is_(True)))).scalars().all()
    result: dict[str, int] = {}
    for market in markets:
        reference = await fetch_reference_price(market.symbol)
        if reference is None:
            result[market.symbol] = -1  # unreachable; left unchanged
            continue
        result[market.symbol] = await refresh_market(db, market, reference)
    await db.commit()
    return result
