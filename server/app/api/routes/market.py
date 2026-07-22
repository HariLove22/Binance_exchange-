"""Market data.

Two sources, deliberately split:

- **The chart** (klines, ticker) is proxied from Binance's free public feed. It is reference price
  history and context — deep, real, and not something we need to reproduce.
- **The order book and recent trades** are OURS — the resting orders on our engine and the fills
  between our users. This is what an order actually executes against. Showing Binance's book here
  would be a lie: users cannot trade against it.

The proxy exists so the browser talks only to our origin (one CORS surface, and we can cache or
rate-limit later) rather than calling Binance directly.
"""

from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import Asset, Market, OPEN_STATUSES, Order, OrderSide, Trade

router = APIRouter(prefix="/market", tags=["market"])

BINANCE = "https://data-api.binance.vision/api/v3"


class MarketInfo(BaseModel):
    symbol: str
    base: str
    quote: str
    price_tick: str
    qty_step: str
    min_notional: str
    maker_fee: str
    taker_fee: str


@router.get("/symbols", response_model=list[MarketInfo])
async def symbols(db: AsyncSession = Depends(get_db)):
    markets = (await db.execute(select(Market).where(Market.enabled.is_(True)).order_by(Market.symbol))).scalars().all()
    out = []
    for m in markets:
        base = await db.get(Asset, m.base_asset_id)
        quote = await db.get(Asset, m.quote_asset_id)
        out.append(MarketInfo(
            symbol=m.symbol, base=base.symbol, quote=quote.symbol,
            price_tick=f"{m.price_tick.normalize():f}", qty_step=f"{m.qty_step.normalize():f}",
            min_notional=f"{m.min_notional.normalize():f}",
            maker_fee=f"{m.maker_fee.normalize():f}", taker_fee=f"{m.taker_fee.normalize():f}",
        ))
    return out


async def _binance_get(path: str, params: dict) -> object:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{BINANCE}{path}", params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"reference feed unavailable: {exc}") from exc


@router.get("/klines")
async def klines(
    symbol: str = Query(...),
    interval: str = Query("1m"),
    limit: int = Query(200, le=1000),
):
    """Candle history, proxied from Binance. Chart context, not our book."""
    return await _binance_get("/klines", {"symbol": symbol.upper(), "interval": interval, "limit": limit})


@router.get("/ticker")
async def ticker(symbol: str = Query(...)):
    """24h ticker for the reference price, proxied from Binance."""
    return await _binance_get("/ticker/24hr", {"symbol": symbol.upper()})


class DepthLevel(BaseModel):
    price: str
    quantity: str


class Depth(BaseModel):
    symbol: str
    bids: list[DepthLevel]  # highest first
    asks: list[DepthLevel]  # lowest first


@router.get("/depth", response_model=Depth)
async def depth(symbol: str = Query(...), limit: int = Query(20, le=100), db: AsyncSession = Depends(get_db)):
    """OUR order book — the resting orders on our engine, aggregated by price. This is what an
    order fills against."""
    market = (await db.execute(select(Market).where(Market.symbol == symbol.upper()))).scalar_one_or_none()
    if market is None:
        raise HTTPException(404, "unknown market")

    async def side(order_side: OrderSide, desc: bool) -> list[DepthLevel]:
        remaining = Order.quantity - Order.filled_quantity
        q = (
            select(Order.price, func.sum(remaining))
            .where(Order.market_id == market.id, Order.side == order_side, Order.status.in_(OPEN_STATUSES))
            .group_by(Order.price)
            .order_by(Order.price.desc() if desc else Order.price.asc())
            .limit(limit)
        )
        return [
            DepthLevel(price=f"{p.normalize():f}", quantity=f"{Decimal(qty).normalize():f}")
            for p, qty in (await db.execute(q)).all()
        ]

    return Depth(symbol=market.symbol, bids=await side(OrderSide.BUY, True), asks=await side(OrderSide.SELL, False))


class TradeTick(BaseModel):
    id: int
    price: str
    quantity: str
    taker_side: str
    created_at: str


@router.get("/trades", response_model=list[TradeTick])
async def trades(symbol: str = Query(...), limit: int = Query(30, le=100), db: AsyncSession = Depends(get_db)):
    """OUR recent trades — real fills between our users."""
    market = (await db.execute(select(Market).where(Market.symbol == symbol.upper()))).scalar_one_or_none()
    if market is None:
        raise HTTPException(404, "unknown market")
    rows = (
        await db.execute(
            select(Trade).where(Trade.market_id == market.id).order_by(Trade.id.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        TradeTick(
            id=t.id, price=f"{t.price.normalize():f}", quantity=f"{t.quantity.normalize():f}",
            taker_side=t.taker_side.value, created_at=t.created_at.isoformat(),
        )
        for t in rows
    ]
