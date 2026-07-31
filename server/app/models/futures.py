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

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
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


class FuturesPosition(Base):
    __tablename__ = "futures_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. BTCUSDT

    side: Mapped[PositionSide] = mapped_column(str_enum(PositionSide, "position_side"), nullable=False)
    size: Mapped[Decimal] = mapped_column(MONEY, nullable=False)          # base quantity
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    leverage: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)        # USDT locked

    status: Mapped[PositionStatus] = mapped_column(
        str_enum(PositionStatus, "position_status"), nullable=False, default=PositionStatus.OPEN
    )
    close_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("size > 0 AND entry_price > 0 AND leverage >= 1 AND margin >= 0", name="ck_futures_positive"),
        Index("ix_futures_open", "status", "symbol"),
        Index("ix_futures_user", "user_id", "id"),
    )

    def notional(self, price: Decimal) -> Decimal:
        return self.size * price

    def pnl_at(self, price: Decimal) -> Decimal:
        """Unrealized/realized PnL at a given price."""
        diff = price - self.entry_price
        return diff * self.size if self.side is PositionSide.LONG else -diff * self.size

    def __repr__(self) -> str:
        return f"<FuturesPosition {self.side.value} {self.size} {self.symbol} @ {self.entry_price} {self.status.value}>"
