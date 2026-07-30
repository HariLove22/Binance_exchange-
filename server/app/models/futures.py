"""Futures trading: leveraged LONG/SHORT positions settled against the mark price.

Unlike spot (you own the asset) or margin (you borrow to trade spot), a futures position is a
contract: you pick a direction and leverage, lock margin = notional / leverage in the FUTURES
sub-wallet, and your PnL tracks the mark price. It closes when you close it, or automatically when
equity falls to the maintenance margin (liquidation).

One-way mode: at most one OPEN position per (user, symbol). Opening the same side adds and averages
the entry; the opposite side reduces or flips. Hedge mode (both sides at once) is a later stage.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import MONEY, TimestampMixin, str_enum


class PositionSide(str, enum.Enum):
    LONG = "LONG"    # profits when the mark price rises
    SHORT = "SHORT"  # profits when the mark price falls


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"          # closed by the user
    LIQUIDATED = "LIQUIDATED"  # force-closed when equity hit maintenance margin


class FuturesPosition(TimestampMixin, Base):
    __tablename__ = "futures_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # The spot market symbol whose price this position marks against, e.g. "BTCUSDT".
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)

    side: Mapped[PositionSide] = mapped_column(str_enum(PositionSide, "position_side"), nullable=False)
    leverage: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    size: Mapped[Decimal] = mapped_column(MONEY, nullable=False)          # contract qty in base (BTC)
    entry_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)   # avg entry (quote per base)
    margin: Mapped[Decimal] = mapped_column(MONEY, nullable=False)        # collateral locked (quote)
    liquidation_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Accumulated on partial closes; unrealized PnL is computed live from the mark price, not stored.
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    status: Mapped[PositionStatus] = mapped_column(
        str_enum(PositionStatus, "position_status"), nullable=False, default=PositionStatus.OPEN
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("leverage >= 1", name="ck_futures_positions_leverage"),
        CheckConstraint("size >= 0 AND margin >= 0", name="ck_futures_positions_nonneg"),
        # One-way mode: at most one OPEN position per user+symbol.
        Index(
            "uq_futures_open_position",
            "user_id",
            "symbol",
            unique=True,
            postgresql_where=(status == PositionStatus.OPEN),
        ),
        Index("ix_futures_positions_user", "user_id", "status"),
        Index("ix_futures_positions_open", "status", "symbol"),
    )

    def __repr__(self) -> str:
        return f"<FuturesPosition {self.side.value} user={self.user_id} {self.symbol} {self.size}@{self.entry_price} {self.leverage}x>"
