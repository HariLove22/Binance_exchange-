"""WebSocket market data — our order book and trades, pushed live.

Public, like the REST depth/trades it mirrors. On connect the client gets a snapshot; after that a
fresh snapshot is pushed whenever an order or trade changes the book (via the pub/sub bus), plus a
periodic heartbeat so a client can tell a quiet market from a dead connection. No client polling.

A snapshot rather than diffs: our books are small (tens of levels) and change infrequently, so the
bandwidth saved by diffing is not worth the well-known bugs of keeping a diff stream in sync. If a
book ever gets large enough to matter, that is the point to switch to sequenced diffs.
"""

import asyncio
import contextlib
from decimal import Decimal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select

from app.core.db import AsyncSessionLocal
from app.models import Market, OPEN_STATUSES, Order, OrderSide, Trade
from app.services import pubsub

router = APIRouter(tags=["ws"])

HEARTBEAT_SECONDS = 3.0
DEPTH = 16


async def _snapshot(db, market: Market) -> dict:
    async def side(order_side: OrderSide, desc: bool):
        remaining = Order.quantity - Order.filled_quantity
        q = (
            select(Order.price, func.sum(remaining))
            .where(Order.market_id == market.id, Order.side == order_side, Order.status.in_(OPEN_STATUSES))
            .group_by(Order.price)
            .order_by(Order.price.desc() if desc else Order.price.asc())
            .limit(DEPTH)
        )
        return [
            {"price": f"{p.normalize():f}", "quantity": f"{Decimal(qty).normalize():f}"}
            for p, qty in (await db.execute(q)).all()
        ]

    trades = (
        await db.execute(select(Trade).where(Trade.market_id == market.id).order_by(Trade.id.desc()).limit(30))
    ).scalars().all()

    return {
        "type": "snapshot",
        "symbol": market.symbol,
        "bids": await side(OrderSide.BUY, True),
        "asks": await side(OrderSide.SELL, False),
        "trades": [
            {
                "id": t.id, "price": f"{t.price.normalize():f}", "quantity": f"{t.quantity.normalize():f}",
                "taker_side": t.taker_side.value, "created_at": t.created_at.isoformat(),
            }
            for t in trades
        ],
    }


@router.websocket("/ws/market/{symbol}")
async def market_ws(websocket: WebSocket, symbol: str) -> None:
    await websocket.accept()
    symbol = symbol.upper()

    async with AsyncSessionLocal() as db:
        market = (await db.execute(select(Market).where(Market.symbol == symbol))).scalar_one_or_none()
        if market is None:
            await websocket.send_json({"type": "error", "message": "unknown market"})
            await websocket.close()
            return

        # Initial snapshot.
        await websocket.send_json(await _snapshot(db, market))

    async with pubsub.subscribe(pubsub.market_channel(symbol)) as queue:
        try:
            while True:
                # Wake on a publish, or fall through on the heartbeat interval.
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)

                # A fresh session each push so the read never sees stale, cached rows.
                async with AsyncSessionLocal() as db:
                    market = (await db.execute(select(Market).where(Market.symbol == symbol))).scalar_one()
                    await websocket.send_json(await _snapshot(db, market))
        except WebSocketDisconnect:
            return
        except RuntimeError:
            # Send after close (client vanished mid-push). Nothing to do.
            return
