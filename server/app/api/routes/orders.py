"""Order placement and matching.

An order is validated, stored, then immediately matched against the resting book. The full
execution report comes back in the POST response.

⚠️ NOT YET DONE — funds are not locked or settled. A trade currently moves no money: it
records *what* was agreed, not the transfer. Before this is anything but a paper exercise,
placing an order must lock the committed asset (quote for BUY, base for SELL) *before* the
matcher can see it, and each fill must post a balanced ledger transaction. The ledger and its
LOCKED accounts already exist (app/services/ledger.py) — the wiring is the missing piece.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.assets import UnknownAsset, split_pair
from app.core.db import get_db
from app.core.money import MoneyError, format_money, from_scaled_int, to_scaled_int
from app.models.order import DEFAULT_PAIR, NEW, Order
from app.models.trade import Trade
from app.models.user import User
from app.schemas.order import FillOut, OrderOut, PlaceOrderRequest
from app.services.matching import match_order

router = APIRouter(prefix="/orders", tags=["orders"])


def _to_out(
    order: Order, price_scale: int, qty_scale: int, trades: list[Trade] | None = None
) -> OrderOut:
    def price(units: int) -> str:
        return format_money(from_scaled_int(units, price_scale), price_scale)

    def qty(units: int) -> str:
        return format_money(from_scaled_int(units, qty_scale), qty_scale)

    return OrderOut(
        order_id=order.order_id,
        pair=order.pair,
        side=order.side,
        price=price(order.price),
        quantity=qty(order.quantity),
        filled_quantity=qty(order.filled_quantity),
        status=order.status,
        created_at=order.created_at,
        fills=[
            FillOut(
                maker_order_id=t.maker_order_id, price=price(t.price), quantity=qty(t.quantity)
            )
            for t in (trades or [])
        ],
    )


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def place_order(
    body: PlaceOrderRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    if body.pair != DEFAULT_PAIR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Only {DEFAULT_PAIR} is supported right now"
        )

    try:
        base, quote = split_pair(body.pair)
    except UnknownAsset as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    # Price is in quote units (USDT), quantity in base units (BTC). to_scaled_int rejects
    # floats and anything carrying more precision than the asset's scale allows.
    try:
        price_units = to_scaled_int(body.price, quote.scale)
    except MoneyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid price: {exc}")
    try:
        qty_units = to_scaled_int(body.quantity, base.scale)
    except MoneyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid quantity: {exc}")

    if price_units <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Price must be greater than zero")
    if qty_units <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Quantity must be greater than zero")

    order = Order(
        user_id=current.id,
        pair=body.pair,
        side=body.side,
        price=price_units,
        quantity=qty_units,
        filled_quantity=0,
        status=NEW,
    )
    db.add(order)
    # flush (not commit) so the order gets its id and can be referenced by trades, while the
    # order + its trades + both sides' status updates still commit as ONE transaction. A crash
    # mid-match must not leave a trade without its order updates.
    await db.flush()

    trades = await match_order(db, order)

    await db.commit()
    await db.refresh(order)

    return _to_out(order, quote.scale, base.scale, trades)
