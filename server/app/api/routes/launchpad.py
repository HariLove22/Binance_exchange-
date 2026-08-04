"""Token launchpad endpoints: create a coin, run an ICO/STO offering, pool it, and swap.

Creation/trading routes are KYC-gated like the rest of the exchange. All money moves through the
services (token_factory / offering / amm), which post balanced ledger transactions.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import (
    AmmPool,
    Asset,
    LaunchedToken,
    LpPosition,
    OfferingType,
    TokenOffering,
    User,
    WALLET_SPOT,
)
from app.services import amm, kyc, ledger, offering, token_factory
from app.services.amm import AmmError
from app.services.kyc import KycRequired
from app.services.offering import OfferingError
from app.services.token_factory import LaunchError

router = APIRouter(prefix="/launchpad", tags=["launchpad"])


def _n(d: Decimal | None) -> str | None:
    return f"{d.normalize():f}" if d is not None else None


def _dec(v: str, field: str) -> Decimal:
    try:
        return Decimal(v)
    except (InvalidOperation, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad number in {field}") from None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _require_kyc(db: AsyncSession, user_id: int) -> None:
    try:
        await kyc.assert_approved(db, user_id)
    except KycRequired as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc


async def _bal(db: AsyncSession, user_id: int, asset_id: int) -> Decimal:
    return (await ledger.get_or_create_account(db, asset_id, ledger.AccountType.AVAILABLE, user_id, wallet=WALLET_SPOT)).balance


# --- create token ---------------------------------------------------------------------------------

class LaunchRequest(BaseModel):
    symbol: str
    name: str
    total_supply: str
    purpose: str = ""
    target_audience: str = ""
    offering_type: OfferingType = OfferingType.ICO


@router.post("/token", status_code=status.HTTP_201_CREATED)
async def create_token(body: LaunchRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_kyc(db, user.id)
    try:
        token = await token_factory.launch(
            db, creator_id=user.id, symbol=body.symbol, name=body.name,
            total_supply=_dec(body.total_supply, "total_supply"), purpose=body.purpose,
            target_audience=body.target_audience, offering_type=body.offering_type,
        )
    except LaunchError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    asset = await db.get(Asset, token.asset_id)
    return {"id": token.id, "symbol": asset.symbol, "name": asset.name,
            "total_supply": _n(token.total_supply), "offering_type": token.offering_type.value,
            "balance": _n(await _bal(db, user.id, token.asset_id))}


@router.get("/tokens")
async def my_tokens(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(LaunchedToken, Asset).join(Asset, Asset.id == LaunchedToken.asset_id)
        .where(LaunchedToken.creator_id == user.id).order_by(LaunchedToken.id.desc())
    )).all()
    return [{"id": t.id, "symbol": a.symbol, "name": a.name, "total_supply": _n(t.total_supply),
             "offering_type": t.offering_type.value, "purpose": t.purpose, "target_audience": t.target_audience,
             "balance": _n(await _bal(db, user.id, t.asset_id))} for t, a in rows]


# --- offering (ICO/STO) ---------------------------------------------------------------------------

class OfferingRequest(BaseModel):
    token_symbol: str
    sale_price: str
    tokens_for_sale: str
    soft_cap: str = "0"
    duration_hours: int = 168
    requires_whitelist: bool = False
    lockup_days: int = 0


async def _token_by_symbol(db: AsyncSession, symbol: str) -> tuple[LaunchedToken, Asset]:
    asset = (await db.execute(select(Asset).where(Asset.symbol == symbol.upper()))).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{symbol} not found")
    token = (await db.execute(select(LaunchedToken).where(LaunchedToken.asset_id == asset.id))).scalar_one_or_none()
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{symbol} is not a launched token")
    return token, asset


@router.post("/offering", status_code=status.HTTP_201_CREATED)
async def open_offering(body: OfferingRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_kyc(db, user.id)
    token, _ = await _token_by_symbol(db, body.token_symbol)
    now = _now()
    lockup = now + timedelta(days=body.lockup_days) if body.lockup_days > 0 else None
    try:
        off = await offering.create_offering(
            db, token=token, creator_id=user.id, sale_price=_dec(body.sale_price, "sale_price"),
            tokens_for_sale=_dec(body.tokens_for_sale, "tokens_for_sale"), soft_cap=_dec(body.soft_cap, "soft_cap"),
            start_at=now, end_at=now + timedelta(hours=body.duration_hours),
            requires_whitelist=body.requires_whitelist, lockup_until=lockup,
        )
    except OfferingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _offering_row(off)


def _offering_row(o: TokenOffering) -> dict:
    return {"id": o.id, "type": o.offering_type.value, "status": o.status.value,
            "sale_price": _n(o.sale_price), "tokens_for_sale": _n(o.tokens_for_sale),
            "hard_cap": _n(o.hard_cap), "soft_cap": _n(o.soft_cap), "raised": _n(o.raised),
            "tokens_sold": _n(o.tokens_sold), "start_at": o.start_at.isoformat(), "end_at": o.end_at.isoformat(),
            "requires_whitelist": o.requires_whitelist,
            "lockup_until": o.lockup_until.isoformat() if o.lockup_until else None}


@router.get("/offerings")
async def list_offerings(db: AsyncSession = Depends(get_db)):
    offs = (await db.execute(select(TokenOffering).order_by(TokenOffering.id.desc()))).scalars().all()
    out = []
    for o in offs:
        asset = await db.get(Asset, o.token_asset_id)
        out.append({**_offering_row(o), "symbol": asset.symbol if asset else "?"})
    return out


class BuyRequest(BaseModel):
    usdt_amount: str


@router.post("/offering/{offering_id}/buy")
async def buy_offering(offering_id: int, body: BuyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_kyc(db, user.id)
    off = await db.get(TokenOffering, offering_id)
    if off is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "offering not found")
    try:
        p = await offering.buy(db, offering=off, user_id=user.id, usdt_amount=_dec(body.usdt_amount, "usdt_amount"), now=_now())
    except OfferingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"tokens_bought": _n(p.tokens_bought), "usdt_paid": _n(p.usdt_paid)}


@router.post("/offering/{offering_id}/close")
async def close_offering_route(offering_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    off = await db.get(TokenOffering, offering_id)
    if off is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "offering not found")
    token = (await db.execute(select(LaunchedToken).where(LaunchedToken.asset_id == off.token_asset_id))).scalar_one()
    if token.creator_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the creator can close the offering")
    result = await offering.close_offering(db, offering=off)
    await db.commit()
    return {"status": result.value}


class WhitelistRequest(BaseModel):
    user_email: str


@router.post("/offering/{offering_id}/whitelist")
async def whitelist_route(offering_id: int, body: WhitelistRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    off = await db.get(TokenOffering, offering_id)
    if off is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "offering not found")
    investor = (await db.execute(select(User).where(User.email == body.user_email))).scalar_one_or_none()
    if investor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "investor not found")
    try:
        await offering.add_to_whitelist(db, offering=off, creator_id=user.id, user_id=investor.id)
    except OfferingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"whitelisted": investor.email}


# --- pools & swap ---------------------------------------------------------------------------------

class PoolRequest(BaseModel):
    token_symbol: str
    token_amt: str
    quote_amt: str


@router.post("/pool", status_code=status.HTTP_201_CREATED)
async def create_and_seed_pool(body: PoolRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Create the token/USDT pool (if needed) and seed initial liquidity in one call — the 'listing'."""
    await _require_kyc(db, user.id)
    token, _ = await _token_by_symbol(db, body.token_symbol)
    try:
        pool = await amm.create_pool(db, token_asset_id=token.asset_id)
        shares = await amm.add_liquidity(db, user_id=user.id, pool=pool,
                                         token_amt=_dec(body.token_amt, "token_amt"), quote_amt=_dec(body.quote_amt, "quote_amt"))
    except AmmError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"pool_id": pool.id, "shares": _n(shares), "price": _n(pool.price())}


async def _pool_row(db: AsyncSession, pool: AmmPool, user_id: int | None) -> dict:
    token = await db.get(Asset, pool.token_asset_id)
    lt = (await db.execute(select(LaunchedToken).where(LaunchedToken.asset_id == pool.token_asset_id))).scalar_one_or_none()
    my_shares = Decimal(0)
    if user_id is not None:
        pos = (await db.execute(
            select(LpPosition).where(LpPosition.pool_id == pool.id, LpPosition.user_id == user_id)
        )).scalar_one_or_none()
        my_shares = pos.shares if pos else Decimal(0)
    price = pool.price()
    return {
        "id": pool.id, "symbol": token.symbol if token else "?", "name": token.name if token else "?",
        "reserve_token": _n(pool.reserve_token), "reserve_quote": _n(pool.reserve_quote),
        "price": _n(price), "fee_bps": pool.fee_bps, "lp_supply": _n(pool.lp_supply),
        "tvl_usd": _n(pool.reserve_quote * 2),                                   # both sides ≈ 2× the quote reserve
        "fdv_usd": _n(amm.fdv(pool, lt.total_supply)) if lt else None,           # coin value: price × total supply
        "my_shares": _n(my_shares),
    }


@router.get("/pools")
async def list_pools(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    pools = (await db.execute(select(AmmPool).order_by(AmmPool.id.desc()))).scalars().all()
    return [await _pool_row(db, p, user.id) for p in pools]


class LiquidityRequest(BaseModel):
    token_amt: str
    quote_amt: str = "0"


@router.post("/pool/{pool_id}/add")
async def add_liquidity_route(pool_id: int, body: LiquidityRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_kyc(db, user.id)
    pool = await db.get(AmmPool, pool_id)
    if pool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pool not found")
    try:
        shares = await amm.add_liquidity(db, user_id=user.id, pool=pool,
                                         token_amt=_dec(body.token_amt, "token_amt"), quote_amt=_dec(body.quote_amt, "quote_amt"))
    except AmmError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"shares": _n(shares), "price": _n(pool.price())}


class RemoveRequest(BaseModel):
    shares: str


@router.post("/pool/{pool_id}/remove")
async def remove_liquidity_route(pool_id: int, body: RemoveRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    pool = await db.get(AmmPool, pool_id)
    if pool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pool not found")
    try:
        tok, quo = await amm.remove_liquidity(db, user_id=user.id, pool=pool, shares=_dec(body.shares, "shares"))
    except AmmError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"token_out": _n(tok), "quote_out": _n(quo)}


@router.get("/swap/quote")
async def swap_quote(pool_id: int = Query(...), side: str = Query(...), amount_in: str = Query(...),
                     db: AsyncSession = Depends(get_db)):
    pool = await db.get(AmmPool, pool_id)
    if pool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pool not found")
    try:
        out, impact = amm.quote_swap(pool, side=side.upper(), amount_in=_dec(amount_in, "amount_in"))
    except AmmError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"amount_out": _n(out), "price_impact": _n(impact)}


class SwapRequest(BaseModel):
    pool_id: int
    side: str            # BUY | SELL
    amount_in: str
    min_out: str = "0"


@router.post("/swap")
async def swap_route(body: SwapRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _require_kyc(db, user.id)
    pool = await db.get(AmmPool, body.pool_id)
    if pool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pool not found")
    try:
        out = await amm.swap(db, user_id=user.id, pool=pool, side=body.side.upper(),
                             amount_in=_dec(body.amount_in, "amount_in"), min_out=_dec(body.min_out, "min_out"), now=_now())
    except (AmmError, OfferingError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"amount_out": _n(out), "price": _n(pool.price())}
