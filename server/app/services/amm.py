"""Constant-product AMM: liquidity pools and swaps for launched tokens, quoted in USDT.

A pool holds two reserves (token, USDT) on the house account under wallet POOL:{id}. The invariant
is `reserve_token * reserve_quote = k`; the spot price is `reserve_quote / reserve_token`. Swapping
moves the reserves along that curve, leaving the fee in the pool as the LP reward. Liquidity
providers own `shares`; adding mints shares in proportion, removing burns them.

Every balance move goes through the ledger, so money is conserved. The pool's `reserve_*` columns
are a cache; `verify_reserves` asserts they equal the ledger truth.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AmmPool, LpPosition, WALLET_SPOT
from app.services import ledger, marketmaker
from app.services.ledger import InsufficientFunds, TransactionKind

QUOTE = "USDT"
DEFAULT_FEE_BPS = 30  # 0.30% to liquidity providers
Q18 = Decimal(1).scaleb(-18)  # the ledger's MONEY scale; keep amounts here so cache == ledger truth


def _q(x: Decimal) -> Decimal:
    return x.quantize(Q18)


class AmmError(Exception):
    """A pool/swap action was refused. Safe to surface to a caller."""


def pool_wallet(pool_id: int) -> str:
    return f"POOL:{pool_id}"


async def _asset(db: AsyncSession, symbol: str) -> Asset:
    a = (await db.execute(select(Asset).where(Asset.symbol == symbol))).scalar_one_or_none()
    if a is None:
        raise AmmError(f"{symbol} is not listed")
    return a


async def get_pool(db: AsyncSession, token_asset_id: int, quote_asset_id: int) -> AmmPool | None:
    return (await db.execute(
        select(AmmPool).where(
            AmmPool.token_asset_id == token_asset_id, AmmPool.quote_asset_id == quote_asset_id
        )
    )).scalar_one_or_none()


async def create_pool(
    db: AsyncSession, *, token_asset_id: int, quote_symbol: str = QUOTE, fee_bps: int = DEFAULT_FEE_BPS
) -> AmmPool:
    """Create an empty token/USDT pool (idempotent — returns the existing one)."""
    quote = await _asset(db, quote_symbol)
    if token_asset_id == quote.id:
        raise AmmError("cannot pool an asset against itself")
    existing = await get_pool(db, token_asset_id, quote.id)
    if existing is not None:
        return existing
    pool = AmmPool(token_asset_id=token_asset_id, quote_asset_id=quote.id, fee_bps=fee_bps)
    db.add(pool)
    await db.flush()
    return pool


async def _lp_position(db: AsyncSession, pool_id: int, user_id: int) -> LpPosition:
    pos = (await db.execute(
        select(LpPosition).where(LpPosition.pool_id == pool_id, LpPosition.user_id == user_id)
    )).scalar_one_or_none()
    if pos is None:
        pos = LpPosition(pool_id=pool_id, user_id=user_id, shares=Decimal(0))
        db.add(pos)
        await db.flush()
    return pos


async def add_liquidity(
    db: AsyncSession, *, user_id: int, pool: AmmPool, token_amt: Decimal, quote_amt: Decimal
) -> Decimal:
    """Deposit token + USDT into the pool and mint LP shares. The first add sets the initial price;
    later adds must match the current ratio (the quote amount is derived from the token amount)."""
    if token_amt <= 0:
        raise AmmError("token amount must be positive")

    token_amt = _q(token_amt)
    if pool.lp_supply == 0:
        if quote_amt <= 0:
            raise AmmError("the first liquidity add must set both token and USDT amounts")
        quote_amt = _q(quote_amt)
        shares = _q((token_amt * quote_amt).sqrt())   # ponytail: no MINIMUM_LIQUIDITY lock (single-venue, internal)
    else:
        # Derive the paired USDT from the pool ratio so k-ratio stays exact.
        quote_amt = _q(token_amt * pool.reserve_quote / pool.reserve_token)
        shares = _q(token_amt / pool.reserve_token * pool.lp_supply)
    if shares <= 0:
        raise AmmError("liquidity too small to mint any shares")

    house = await marketmaker.get_market_maker(db)
    wallet = pool_wallet(pool.id)
    try:
        await ledger.transfer_between(
            db, from_user_id=user_id, from_wallet=WALLET_SPOT, to_user_id=house.id, to_wallet=wallet,
            asset_id=pool.token_asset_id, amount=token_amt, kind=TransactionKind.ADJUSTMENT,
            idempotency_key=f"lp-add-tok:{pool.id}:{user_id}:{pool.lp_supply}",
            reference=f"pool {pool.id} add",
        )
        await ledger.transfer_between(
            db, from_user_id=user_id, from_wallet=WALLET_SPOT, to_user_id=house.id, to_wallet=wallet,
            asset_id=pool.quote_asset_id, amount=quote_amt, kind=TransactionKind.ADJUSTMENT,
            idempotency_key=f"lp-add-quo:{pool.id}:{user_id}:{pool.lp_supply}",
            reference=f"pool {pool.id} add",
        )
    except InsufficientFunds as exc:
        raise AmmError(str(exc)) from exc

    pool.reserve_token += token_amt
    pool.reserve_quote += quote_amt
    pool.lp_supply += shares
    pos = await _lp_position(db, pool.id, user_id)
    pos.shares += shares
    return shares


def quote_swap(pool: AmmPool, *, side: str, amount_in: Decimal) -> tuple[Decimal, Decimal]:
    """Compute (amount_out, price_impact) for a swap, without touching the DB.

    side='BUY'  -> pay USDT, receive token.   side='SELL' -> pay token, receive USDT.
    Constant product with the fee kept in the pool: amount_out = in*(1-f)*R_out / (R_in + in*(1-f)).
    """
    if amount_in <= 0:
        raise AmmError("amount must be positive")
    if pool.reserve_token <= 0 or pool.reserve_quote <= 0:
        raise AmmError("pool has no liquidity")
    f = Decimal(pool.fee_bps) / Decimal(10000)
    in_after = amount_in * (1 - f)
    if side == "BUY":
        r_in, r_out = pool.reserve_quote, pool.reserve_token
        spot = pool.reserve_quote / pool.reserve_token          # USDT per token
    elif side == "SELL":
        r_in, r_out = pool.reserve_token, pool.reserve_quote
        spot = pool.reserve_token / pool.reserve_quote          # token per USDT
    else:
        raise AmmError("side must be BUY or SELL")
    amount_out = _q(in_after * r_out / (r_in + in_after))        # snap to the ledger scale (18dp)
    if amount_out <= 0:
        raise AmmError("amount too small to receive anything")
    exec_price = amount_in / amount_out                          # in per out
    price_impact = (exec_price - spot) / spot if spot > 0 else Decimal(0)
    return amount_out, price_impact


async def swap(
    db: AsyncSession, *, user_id: int, pool: AmmPool, side: str, amount_in: Decimal,
    min_out: Decimal, now, offering_svc=None,
) -> Decimal:
    """Execute a swap against the pool. Enforces slippage (min_out) and STO trade rules."""
    amount_in = _q(amount_in)
    amount_out, _ = quote_swap(pool, side=side, amount_in=amount_in)
    if amount_out < min_out:
        raise AmmError(f"slippage: would receive {amount_out}, below min {min_out}")

    # STO compliance: a security token can't be traded while locked or by a non-whitelisted user.
    from app.services import offering as offering_module
    svc = offering_svc or offering_module
    await svc.assert_tradeable(db, token_asset_id=pool.token_asset_id, user_id=user_id, now=now)

    house = await marketmaker.get_market_maker(db)
    wallet = pool_wallet(pool.id)
    if side == "BUY":
        pay_asset, get_asset, get_amt = pool.quote_asset_id, pool.token_asset_id, amount_out
    else:
        pay_asset, get_asset, get_amt = pool.token_asset_id, pool.quote_asset_id, amount_out

    try:
        await ledger.transfer_between(
            db, from_user_id=user_id, from_wallet=WALLET_SPOT, to_user_id=house.id, to_wallet=wallet,
            asset_id=pay_asset, amount=amount_in, kind=TransactionKind.TRADE,
            idempotency_key=f"swap-in:{pool.id}:{user_id}:{amount_in}:{pool.reserve_token}",
            reference=f"pool {pool.id} swap {side}",
        )
    except InsufficientFunds as exc:
        raise AmmError(str(exc)) from exc
    await ledger.transfer_between(
        db, from_user_id=house.id, from_wallet=wallet, to_user_id=user_id, to_wallet=WALLET_SPOT,
        asset_id=get_asset, amount=get_amt, kind=TransactionKind.TRADE,
        idempotency_key=f"swap-out:{pool.id}:{user_id}:{amount_in}:{pool.reserve_token}",
        reference=f"pool {pool.id} swap {side}",
    )

    if side == "BUY":
        pool.reserve_quote += amount_in
        pool.reserve_token -= amount_out
    else:
        pool.reserve_token += amount_in
        pool.reserve_quote -= amount_out
    return amount_out


async def remove_liquidity(
    db: AsyncSession, *, user_id: int, pool: AmmPool, shares: Decimal
) -> tuple[Decimal, Decimal]:
    """Burn LP shares and withdraw the proportional token + USDT back to the provider."""
    if shares <= 0:
        raise AmmError("shares must be positive")
    pos = (await db.execute(
        select(LpPosition).where(LpPosition.pool_id == pool.id, LpPosition.user_id == user_id)
    )).scalar_one_or_none()
    if pos is None or pos.shares < shares:
        raise AmmError("not enough LP shares")

    token_out = _q(pool.reserve_token * shares / pool.lp_supply)
    quote_out = _q(pool.reserve_quote * shares / pool.lp_supply)

    house = await marketmaker.get_market_maker(db)
    wallet = pool_wallet(pool.id)
    await ledger.transfer_between(
        db, from_user_id=house.id, from_wallet=wallet, to_user_id=user_id, to_wallet=WALLET_SPOT,
        asset_id=pool.token_asset_id, amount=token_out, kind=TransactionKind.ADJUSTMENT,
        idempotency_key=f"lp-rem-tok:{pool.id}:{user_id}:{pool.lp_supply}",
        reference=f"pool {pool.id} remove",
    )
    await ledger.transfer_between(
        db, from_user_id=house.id, from_wallet=wallet, to_user_id=user_id, to_wallet=WALLET_SPOT,
        asset_id=pool.quote_asset_id, amount=quote_out, kind=TransactionKind.ADJUSTMENT,
        idempotency_key=f"lp-rem-quo:{pool.id}:{user_id}:{pool.lp_supply}",
        reference=f"pool {pool.id} remove",
    )
    pool.reserve_token -= token_out
    pool.reserve_quote -= quote_out
    pool.lp_supply -= shares
    pos.shares -= shares
    return token_out, quote_out


def fdv(pool: AmmPool, total_supply: Decimal) -> Decimal | None:
    """Fully-diluted valuation = spot price × total supply (the coin's 'value')."""
    price = pool.price()
    return price * total_supply if price is not None else None


async def verify_reserves(db: AsyncSession, pool: AmmPool) -> bool:
    """Self-check: the cached reserves equal the pool wallet's actual ledger balances."""
    house = await marketmaker.get_market_maker(db)
    wallet = pool_wallet(pool.id)
    tok = (await ledger.get_or_create_account(db, pool.token_asset_id, ledger.AccountType.AVAILABLE, house.id, wallet=wallet)).balance
    quo = (await ledger.get_or_create_account(db, pool.quote_asset_id, ledger.AccountType.AVAILABLE, house.id, wallet=wallet)).balance
    return tok == pool.reserve_token and quo == pool.reserve_quote
