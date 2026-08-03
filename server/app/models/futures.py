"""Perpetual futures positions (USDT-M, cash-settled).

A position is a leveraged bet on a symbol, not asset ownership: LONG profits when price rises, SHORT
when it falls. Margin (USDT) is locked in the FUTURES wallet while it's open; realized PnL settles
against the insurance pool on close. Mark price (the live index) drives PnL and, later, liquidation.

ponytail: Stage 1 fills at the mark price against the house (insurance) pool — no order book yet.
Add peer-to-peer matching when volume justifies it.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import MONEY, str_enum


class PositionSide(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LIQUIDATED = "LIQUIDATED"


class FuturesOrderType(str, enum.Enum):
    LIMIT = "LIMIT"                # rests until the last price reaches `price`, then opens at `price`
    STOP_MARKET = "STOP_MARKET"    # (Phase B) triggers at `price`, then opens/closes at market
    TAKE_PROFIT = "TAKE_PROFIT"    # (Phase B) reduce-only trigger to take profit


class FuturesOrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class FuturesOrder(Base):
    """A resting futures order. No peer book here — it fills against the house when the live price
    reaches its price, executed through the normal open/close path (see services.futures)."""

    __tablename__ = "futures_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[PositionSide] = mapped_column(str_enum(PositionSide, "position_side"), nullable=False)
    order_type: Mapped[FuturesOrderType] = mapped_column(str_enum(FuturesOrderType, "futures_order_type"), nullable=False)

    size: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)   # limit price (LIMIT) / trigger (STOP/TP)
    leverage: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    inverse: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    cross: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)

    status: Mapped[FuturesOrderStatus] = mapped_column(
        str_enum(FuturesOrderStatus, "futures_order_status"), nullable=False, default=FuturesOrderStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("size > 0 AND price > 0 AND leverage >= 1", name="ck_futures_orders_positive"),
        Index("ix_futures_orders_open", "status", "symbol"),
        Index("ix_futures_orders_user", "user_id", "id"),
    )


class FuturesPosition(Base):
    __tablename__ = "futures_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. BTCUSDT

    side: Mapped[PositionSide] = mapped_column(str_enum(PositionSide, "position_side"), nullable=False)
    # Linear (USDT-M): size is base quantity, PnL/margin in USDT. Inverse (COIN-M): size is USD
    # notional, PnL/margin in the base coin.
    inverse: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    # Cross margin: the whole futures wallet (plus other cross positions' equity) backs this position,
    # and the cross bucket liquidates as a group. Isolated (default): only this position's margin is at
    # risk and it liquidates on its own.
    cross: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", default=False)
    margin_asset: Mapped[str] = mapped_column(String(12), nullable=False, server_default="USDT", default="USDT")
    size: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    leverage: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)        # in margin_asset

    status: Mapped[PositionStatus] = mapped_column(
        str_enum(PositionStatus, "position_status"), nullable=False, default=PositionStatus.OPEN
    )
    close_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    # Perpetual funding: at each interval longs pay shorts (or vice versa) via the insurance pool.
    # last_funding_at advances one interval each time funding is charged; funding_accrued is the
    # running net paid(-)/received(+) for display.
    last_funding_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    funding_accrued: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0), server_default="0")

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("size > 0 AND entry_price > 0 AND leverage >= 1 AND margin >= 0", name="ck_futures_positive"),
        Index("ix_futures_open", "status", "symbol"),
        Index("ix_futures_user", "user_id", "id"),
    )

    def notional(self, price: Decimal) -> Decimal:
        """Position notional in the margin asset: USD (linear) or coin (inverse)."""
        return self.size / price if self.inverse else self.size * price

    def pnl_at(self, price: Decimal) -> Decimal:
        """Unrealized/realized PnL at a price, in the margin asset (USDT linear / coin inverse)."""
        if self.inverse:
            # coin PnL = notional_usd × (1/entry − 1/price)
            base = self.size * (Decimal(1) / self.entry_price - Decimal(1) / price)
        else:
            base = (price - self.entry_price) * self.size
        return base if self.side is PositionSide.LONG else -base

    def __repr__(self) -> str:
        return f"<FuturesPosition {self.side.value} {self.size} {self.symbol} @ {self.entry_price} {self.status.value}>"
