"""The matching engine and order lifecycle.

Design choice for this stage: **DB-backed, synchronous matching, serialized per symbol** with a
Postgres advisory lock. Not an in-memory engine in a separate process — that is the right end
state, but it is premature now. We are liquidity-constrained, not latency-constrained: a handful
of markets doing a handful of orders per second do not need microsecond matching, and a DB-backed
engine has no in-memory state to lose, no separate process to run, and no worker-divergence to
reason about. When throughput actually demands it, the deterministic core ports to an in-memory
engine — that is a good problem to have, not today's.

The rules that are NOT negotiable and carry over to any future engine:

- **Price-time priority.** Best price first; among equal prices, the earlier order (smaller id).
- **Trade at the maker's price.** The resting order's price is honoured; improvement goes to the
  taker. A taker therefore locks *exactly* the fill cost, so there is no over-lock to refund.
- **Lock before match.** Funds move AVAILABLE -> LOCKED before any fill, so a trade can never be
  produced that the ledger cannot settle.
- **Decimal, never float.** A rounding error in a fill is a customer-visible loss.
- **Serialize per symbol.** One advisory lock per market means two orders on the same symbol
  cannot interleave and double-spend the same resting liquidity.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    OPEN_STATUSES,
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Trade,
)
from app.services import ledger
from app.services.ledger import InsufficientFunds


class TradingError(Exception):
    """An order was rejected. Safe to surface to a caller."""


def _is_multiple(value: Decimal, step: Decimal) -> bool:
    return (value % step) == 0


def _validate(market: Market, side: OrderSide, order_type: OrderType, price: Decimal | None, quantity: Decimal) -> None:
    if quantity <= 0:
        raise TradingError("quantity must be positive")
    if not _is_multiple(quantity, market.qty_step):
        raise TradingError(f"quantity must be a multiple of {market.qty_step}")
    if order_type is OrderType.LIMIT:
        if price is None or price <= 0:
            raise TradingError("limit orders require a positive price")
        if not _is_multiple(price, market.price_tick):
            raise TradingError(f"price must be a multiple of {market.price_tick}")
        if price * quantity < market.min_notional:
            raise TradingError(f"order value below minimum of {market.min_notional}")


@dataclass
class _Fill:
    maker: Order
    price: Decimal
    quantity: Decimal


async def _resting_book(db: AsyncSession, market_id: int, taker_side: OrderSide) -> list[Order]:
    """The opposite side's open orders, in match order: best price first, then oldest (id)."""
    if taker_side is OrderSide.BUY:
        # Match against asks: lowest price first.
        opposite, price_order = OrderSide.SELL, Order.price.asc()
    else:
        # Match against bids: highest price first.
        opposite, price_order = OrderSide.BUY, Order.price.desc()

    return list(
        (
            await db.execute(
                select(Order)
                .where(
                    Order.market_id == market_id,
                    Order.side == opposite,
                    Order.status.in_(OPEN_STATUSES),
                )
                .order_by(price_order, Order.id.asc())
                .with_for_update()
            )
        ).scalars().all()
    )


def _crosses(taker_side: OrderSide, taker_price: Decimal | None, maker_price: Decimal) -> bool:
    if taker_price is None:  # MARKET takes any price
        return True
    return maker_price <= taker_price if taker_side is OrderSide.BUY else maker_price >= taker_price


def _dry_run(taker_side: OrderSide, taker_price: Decimal | None, quantity: Decimal, book: list[Order]) -> list[_Fill]:
    """Walk the book and compute the fills, without mutating anything."""
    remaining = quantity
    fills: list[_Fill] = []
    for maker in book:
        if remaining <= 0:
            break
        if not _crosses(taker_side, taker_price, maker.price):
            break  # price-sorted, so nothing further crosses either
        take = min(remaining, maker.remaining)
        if take <= 0:
            continue
        fills.append(_Fill(maker=maker, price=maker.price, quantity=take))
        remaining -= take
    return fills


@dataclass(frozen=True)
class PlacedOrder:
    order: Order
    trades: list[Trade]


async def place_order(
    db: AsyncSession,
    *,
    user_id: int,
    market: Market,
    side: OrderSide,
    order_type: OrderType,
    quantity: Decimal,
    price: Decimal | None = None,
) -> PlacedOrder:
    if not market.enabled:
        raise TradingError("market is not open for trading")
    _validate(market, side, order_type, price, quantity)

    # Serialize everything on this symbol. Two orders on the same market cannot interleave and
    # spend the same resting liquidity twice.
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": market.id})

    book = await _resting_book(db, market.id, side)
    fills = _dry_run(side, price, quantity, book)

    filled_qty = sum((f.quantity for f in fills), Decimal(0))
    fill_cost = sum((f.price * f.quantity for f in fills), Decimal(0))
    residual = quantity - filled_qty

    # What the taker must lock. Trades settle at maker prices, so a taker locks exactly the fill
    # cost — no over-lock. A LIMIT residual additionally locks at the limit price to rest.
    if side is OrderSide.BUY:
        locked_asset_id = market.quote_asset_id
        lock_amount = fill_cost + (price * residual if order_type is OrderType.LIMIT else Decimal(0))
    else:
        locked_asset_id = market.base_asset_id
        # A sell reserves base: everything that fills, plus the residual that rests (LIMIT only).
        lock_amount = filled_qty + (residual if order_type is OrderType.LIMIT else Decimal(0))

    if lock_amount <= 0:
        # A market order with nothing to fill (empty book). Reject rather than rest.
        raise TradingError("no liquidity available to fill this order")

    # Create the order first so its id can key the fund lock. The lock still happens before any
    # fill is produced — "lock before match" — which is the invariant that matters; the empty row
    # existing for a few statements before its funds are locked changes nothing, because matching
    # has not run and no trade can reference it yet.
    order = Order(
        user_id=user_id,
        market_id=market.id,
        side=side,
        type=order_type,
        price=price,
        quantity=quantity,
        filled_quantity=Decimal(0),
        status=OrderStatus.NEW,
        locked_asset_id=locked_asset_id,
        locked_remaining=Decimal(0),
    )
    db.add(order)
    await db.flush()

    try:
        await ledger.lock(
            db,
            user_id=user_id,
            asset_id=locked_asset_id,
            amount=lock_amount,
            idempotency_key=f"order-lock:{order.id}",
            reference=f"order={order.id}",
        )
    except InsufficientFunds as exc:
        raise TradingError(str(exc)) from exc
    order.locked_remaining = lock_amount

    trades: list[Trade] = []
    for fill in fills:
        trades.append(await _execute_fill(db, market, taker=order, taker_side=side, fill=fill))

    order.filled_quantity = filled_qty
    if order.remaining == 0:
        order.status = OrderStatus.FILLED
    elif order_type is OrderType.MARKET:
        # No residual rests for a market order — release whatever is still locked (there should be
        # none, since a market taker locks only the fill cost) and finalise.
        await _release_lock(db, order)
        order.status = OrderStatus.FILLED if filled_qty == quantity else OrderStatus.CANCELED
    else:
        order.status = OrderStatus.PARTIALLY_FILLED if filled_qty > 0 else OrderStatus.NEW

    return PlacedOrder(order=order, trades=trades)


async def _execute_fill(db: AsyncSession, market: Market, *, taker: Order, taker_side: OrderSide, fill: _Fill) -> Trade:
    maker = fill.maker
    price, qty = fill.price, fill.quantity
    quote_amount = price * qty

    # Identify buyer/seller and who is the taker, to apply the right fee to each side.
    if taker_side is OrderSide.BUY:
        buyer, seller = taker, maker
        buyer_rate, seller_rate = market.taker_fee, market.maker_fee
    else:
        buyer, seller = maker, taker
        buyer_rate, seller_rate = market.maker_fee, market.taker_fee

    buyer_fee = qty * buyer_rate            # buyer receives base, pays fee in base
    seller_fee = quote_amount * seller_rate  # seller receives quote, pays fee in quote

    trade = Trade(
        market_id=market.id,
        price=price,
        quantity=qty,
        maker_order_id=maker.id,
        taker_order_id=taker.id,
        taker_side=taker_side,
    )
    db.add(trade)
    await db.flush()

    txn = await ledger.settle_trade(
        db,
        base_asset_id=market.base_asset_id,
        quote_asset_id=market.quote_asset_id,
        buyer_id=buyer.user_id,
        seller_id=seller.user_id,
        price=price,
        quantity=qty,
        buyer_fee=buyer_fee,
        seller_fee=seller_fee,
        idempotency_key=f"trade:{trade.id}",
        reference=f"trade={trade.id}",
    )
    if txn is not None:
        trade.ledger_txn_id = txn.id

    # Consume each side's lock by what this fill used: buyer's quote at the trade price, seller's
    # base by the quantity.
    _consume_lock(buyer, quote_amount)
    _consume_lock(seller, qty)

    # Advance the maker's own state.
    maker.filled_quantity = maker.filled_quantity + qty
    if maker.remaining == 0:
        maker.status = OrderStatus.FILLED
    else:
        maker.status = OrderStatus.PARTIALLY_FILLED

    return trade


def _consume_lock(order: Order, amount: Decimal) -> None:
    order.locked_remaining = order.locked_remaining - amount
    if order.locked_remaining < 0:
        # Should be impossible with exact locking; guard so a bug surfaces loudly rather than
        # silently unlocking money that was never there.
        raise TradingError(f"lock underflow on order {order.id}")


async def _release_lock(db: AsyncSession, order: Order) -> None:
    """Return an order's remaining locked funds to AVAILABLE. Used on cancel and market residual."""
    if order.locked_remaining <= 0 or order.locked_asset_id is None:
        return
    await ledger.unlock(
        db,
        user_id=order.user_id,
        asset_id=order.locked_asset_id,
        amount=order.locked_remaining,
        idempotency_key=f"order-unlock:{order.id}",
    )
    order.locked_remaining = Decimal(0)


async def cancel_order(db: AsyncSession, *, user_id: int, order_id: int) -> Order:
    order = (
        await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None or order.user_id != user_id:
        raise TradingError("order not found")
    if order.status not in OPEN_STATUSES:
        raise TradingError(f"cannot cancel an order in status {order.status.value}")

    # Serialize with matching on this symbol so a cancel and a fill cannot race.
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": order.market_id})

    await _release_lock(db, order)
    order.status = OrderStatus.CANCELED
    return order
