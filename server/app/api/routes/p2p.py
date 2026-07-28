"""P2P endpoints: post/list ads, open orders, and drive the escrow lifecycle.

Each money-moving action commits inside one request/transaction, so if anything raises the escrow
never half-moves. Ads are public to browse; every order action is authorization-checked in the
service by party (buyer / seller / admin), not here.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_user, get_current_user
from app.core.db import get_db
from app.models import Asset, P2PAd, P2PAdStatus, P2POrder, P2PSide, User
from app.services import p2p
from app.services.p2p import P2PError

router = APIRouter(prefix="/p2p", tags=["p2p"])


def _dec(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad number in {field}") from None


# --- schemas --------------------------------------------------------------------------------------

class AdRequest(BaseModel):
    side: P2PSide
    asset: str           # crypto symbol, e.g. USDT
    fiat: str            # e.g. INR
    price: str           # fiat per 1 crypto
    min_fiat: str
    max_fiat: str
    total_qty: str       # crypto to make available
    payment_methods: str  # comma-separated
    terms: str | None = None


class AdResponse(BaseModel):
    id: int
    maker_id: int
    side: str
    asset: str
    fiat: str
    price: str
    min_fiat: str
    max_fiat: str
    available_qty: str
    payment_methods: list[str]
    terms: str | None
    status: str


class OrderRequest(BaseModel):
    ad_id: int
    fiat_amount: str
    payment_method: str


class OrderResponse(BaseModel):
    id: int
    ad_id: int
    side_for_me: str        # "BUY" or "SELL" from the caller's perspective
    counterparty_id: int
    asset: str
    fiat: str
    price: str
    crypto_amount: str
    fiat_amount: str
    payment_method: str
    status: str


class ResolveRequest(BaseModel):
    in_favor_of_buyer: bool


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


async def _asset(db: AsyncSession, symbol: str) -> Asset:
    asset = (await db.execute(select(Asset).where(Asset.symbol == symbol.upper()))).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown asset {symbol!r}")
    return asset


def _ad_response(ad: P2PAd, symbol: str) -> AdResponse:
    return AdResponse(
        id=ad.id, maker_id=ad.maker_id, side=ad.side.value, asset=symbol, fiat=ad.fiat,
        price=_n(ad.price), min_fiat=_n(ad.min_fiat), max_fiat=_n(ad.max_fiat),
        available_qty=_n(ad.available_qty),
        payment_methods=[m.strip() for m in ad.payment_methods.split(",") if m.strip()],
        terms=ad.terms, status=ad.status.value,
    )


def _order_response(order: P2POrder, symbol: str, viewer_id: int) -> OrderResponse:
    return OrderResponse(
        id=order.id, ad_id=order.ad_id,
        side_for_me="SELL" if viewer_id == order.seller_id else "BUY",
        counterparty_id=order.buyer_id if viewer_id == order.seller_id else order.seller_id,
        asset=symbol, fiat=order.fiat, price=_n(order.price), crypto_amount=_n(order.crypto_amount),
        fiat_amount=_n(order.fiat_amount), payment_method=order.payment_method, status=order.status.value,
    )


# --- ads ------------------------------------------------------------------------------------------

@router.get("/ads", response_model=list[AdResponse])
async def browse_ads(
    db: AsyncSession = Depends(get_db),
    asset: str | None = Query(None),
    fiat: str | None = Query(None),
    side: P2PSide | None = Query(None),
):
    asset_id = (await _asset(db, asset)).id if asset else None
    ads = await p2p.browse_ads(db, asset_id=asset_id, fiat=fiat, side=side)
    symbols = {a.id: a.symbol for a in (await db.execute(select(Asset))).scalars().all()}
    return [_ad_response(ad, symbols.get(ad.asset_id, "?")) for ad in ads]


@router.post("/ads", response_model=AdResponse, status_code=status.HTTP_201_CREATED)
async def post_ad(body: AdRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    asset = await _asset(db, body.asset)
    try:
        ad = await p2p.create_ad(
            db, maker_id=user.id, side=body.side, asset_id=asset.id, fiat=body.fiat,
            price=_dec(body.price, "price"), min_fiat=_dec(body.min_fiat, "min_fiat"),
            max_fiat=_dec(body.max_fiat, "max_fiat"), total_qty=_dec(body.total_qty, "total_qty"),
            payment_methods=body.payment_methods, terms=body.terms,
        )
    except P2PError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _ad_response(ad, asset.symbol)


@router.post("/ads/{ad_id}/close", response_model=AdResponse)
async def close_ad(ad_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        ad = await p2p.set_ad_status(db, maker_id=user.id, ad_id=ad_id, status=P2PAdStatus.CLOSED)
    except P2PError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    asset = await db.get(Asset, ad.asset_id)
    await db.commit()
    return _ad_response(ad, asset.symbol)


# --- orders ---------------------------------------------------------------------------------------

async def _order_action(db, action, user_id: int, **kwargs) -> OrderResponse:
    try:
        order = await action(db, **kwargs)
    except P2PError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    asset = await db.get(Asset, order.asset_id)
    await db.commit()
    return _order_response(order, asset.symbol, user_id)


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def open_order(body: OrderRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _order_action(
        db, p2p.open_order, user.id,
        taker_id=user.id, ad_id=body.ad_id, fiat_amount=_dec(body.fiat_amount, "fiat_amount"),
        payment_method=body.payment_method,
    )


@router.get("/orders", response_model=list[OrderResponse])
async def my_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    open_only: bool = Query(False),
):
    orders = await p2p.my_orders(db, user_id=user.id, open_only=open_only)
    symbols = {a.id: a.symbol for a in (await db.execute(select(Asset))).scalars().all()}
    return [_order_response(o, symbols.get(o.asset_id, "?"), user.id) for o in orders]


@router.post("/orders/{order_id}/paid", response_model=OrderResponse)
async def mark_paid(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _order_action(db, p2p.mark_paid, user.id, user_id=user.id, order_id=order_id)


@router.post("/orders/{order_id}/release", response_model=OrderResponse)
async def release(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _order_action(db, p2p.release, user.id, user_id=user.id, order_id=order_id)


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
async def cancel(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _order_action(db, p2p.cancel, user.id, user_id=user.id, order_id=order_id)


@router.post("/orders/{order_id}/dispute", response_model=OrderResponse)
async def dispute(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _order_action(db, p2p.open_dispute, user.id, user_id=user.id, order_id=order_id)


@router.post("/orders/{order_id}/resolve", response_model=OrderResponse)
async def resolve(
    order_id: int,
    body: ResolveRequest,
    admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await _order_action(
        db, p2p.resolve_dispute, admin.id, admin=admin, order_id=order_id,
        in_favor_of_buyer=body.in_favor_of_buyer,
    )
