"""Markets, orders and trades — the trading core.

A market is a pair like ETHUSDT: a base asset (ETH) priced in a quote asset (USDT). Orders buy or
sell the base; trades are the fills between them. Settlement of every trade goes through the
ledger, so a trade is two balance movements that sum to zero per asset — the same discipline as
everything else that touches money.

Time priority uses the order's own id, which is monotonic — the earlier order has the smaller id.
No separate sequence column is needed. Prices and quantities are NUMERIC, never float; a rounding
error in a fill is a customer-visible loss.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.asset import MONEY, TimestampMixin, str_enum


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    # Conditional orders. They rest OUTSIDE the book (no matching) until the reference price crosses
    # the trigger, then they become a real LIMIT / MARKET order and match. Stop-loss and take-profit
    # are the same mechanism — the difference is only which side of the current price the trigger is.
    STOP_LIMIT = "STOP_LIMIT"
    STOP_MARKET = "STOP_MARKET"


STOP_TYPES = frozenset({OrderType.STOP_LIMIT, OrderType.STOP_MARKET})


class OrderStatus(str, enum.Enum):
    """NEW -> PARTIALLY_FILLED -> FILLED, or CANCELED / REJECTED.

    A resting order is NEW or PARTIALLY_FILLED and has locked funds; the terminal states have
    released everything. That invariant is what the cancel path and the trial balance both rely on.
    """

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    # A stop order waiting for its trigger. Holds no locked funds and is not in the book; when the
    # trigger fires it becomes NEW and goes through the normal lock+match path.
    TRIGGER_PENDING = "TRIGGER_PENDING"


OPEN_STATUSES = frozenset({OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED})
# Cancellable states: resting book orders and un-triggered stops.
CANCELLABLE_STATUSES = OPEN_STATUSES | {OrderStatus.TRIGGER_PENDING}


class Market(TimestampMixin, Base):
    """A tradeable pair. `symbol` is base+quote, e.g. ETHUSDT."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    base_asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    quote_asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)

    # Trading filters, mirroring Binance's PRICE_FILTER / LOT_SIZE / MIN_NOTIONAL. A price must be a
    # multiple of price_tick, a quantity a multiple of qty_step, and price*qty at least min_notional.
    price_tick: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.01"))
    qty_step: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.0001"))
    min_notional: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("1"))

    # Charged on what each side receives. Maker (resting) pays less than taker (aggressor) — the
    # asymmetry is what pays market makers to provide the liquidity the book needs.
    maker_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.001"))
    taker_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.001"))

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint("base_asset_id <> quote_asset_id", name="ck_markets_distinct_assets"),
        CheckConstraint("price_tick > 0 AND qty_step > 0 AND min_notional >= 0", name="ck_markets_positive_filters"),
    )

    def __repr__(self) -> str:
        return f"<Market {self.symbol}>"


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False)

    side: Mapped[OrderSide] = mapped_column(str_enum(OrderSide, "order_side"), nullable=False)
    type: Mapped[OrderType] = mapped_column(str_enum(OrderType, "order_type"), nullable=False)

    # NULL for MARKET orders. For LIMIT (and STOP_LIMIT once triggered), the worst acceptable price.
    price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    # Stop orders only. `trigger_price` is the level that arms the order; `trigger_above` says which
    # way the price must move to fire — True: fire when the reference price rises to/through the
    # trigger, False: when it falls to/through it. Inferred from the price at placement, so a stop
    # set below the market is a downside stop-loss and one above is an upside take-profit/breakout.
    trigger_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    trigger_above: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    filled_quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    status: Mapped[OrderStatus] = mapped_column(
        str_enum(OrderStatus, "order_status"), nullable=False, default=OrderStatus.NEW
    )

    # How much is still locked for this order. Set when funds are reserved, decremented as fills
    # consume it, released on cancel or completion. The release path reads exactly this — so it can
    # never release more or less than remains.
    locked_asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    locked_remaining: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint("filled_quantity >= 0 AND filled_quantity <= quantity", name="ck_orders_filled_range"),
        CheckConstraint(
            "(type IN ('MARKET', 'STOP_MARKET')) OR (price IS NOT NULL AND price > 0)",
            name="ck_orders_limit_has_price",
        ),
        CheckConstraint(
            "(type IN ('STOP_LIMIT', 'STOP_MARKET')) = (trigger_price IS NOT NULL)",
            name="ck_orders_stop_has_trigger",
        ),
        # Finding the resting book for a symbol is the hot query on every order.
        Index("ix_orders_book", "market_id", "status", "side", "price", "id"),
        Index("ix_orders_user", "user_id", "id"),
    )

    @property
    def remaining(self) -> Decimal:
        return self.quantity - self.filled_quantity

    def __repr__(self) -> str:
        return f"<Order {self.id} {self.side.value} {self.type.value} {self.quantity}@{self.price}>"


class Trade(Base):
    """One fill between a resting (maker) order and an incoming (taker) order.

    Executed at the **maker's** price — the resting order's price is honoured, and any improvement
    accrues to the taker. Recorded immutably; the ledger transaction that settled it is linked so
    the money movement of any trade is reconstructible.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False)

    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    maker_order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False)
    taker_order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False)
    taker_side: Mapped[OrderSide] = mapped_column(str_enum(OrderSide, "trade_taker_side"), nullable=False)

    ledger_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("price > 0 AND quantity > 0", name="ck_trades_positive"),
        Index("ix_trades_market", "market_id", "id"),
    )
