"""European options positions (cash-settled, USDT).

A user buys a call or put on an underlying at a strike, expiring at a datetime. The house is the
writer. At expiry it settles in cash against the mark price: a call pays max(0, mark-strike)*size, a
put max(0, strike-mark)*size; out-of-the-money expires worthless (the premium was the house's gain).

ponytail: no separate contract catalog — the (underlying, strike, expiry, type) tuple on each bought
position *is* the contract. Strikes/expiries are generated in the API, not stored.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import MONEY, str_enum


class OptionType(str, enum.Enum):
    CALL = "CALL"
    PUT = "PUT"


class OptionStatus(str, enum.Enum):
    OPEN = "OPEN"
    EXERCISED = "EXERCISED"  # expired in-the-money, paid out
    EXPIRED = "EXPIRED"      # expired worthless


class OptionPosition(Base):
    __tablename__ = "option_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    underlying: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. BTC
    type: Mapped[OptionType] = mapped_column(str_enum(OptionType, "option_type"), nullable=False)
    strike: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    size: Mapped[Decimal] = mapped_column(MONEY, nullable=False)          # units of underlying
    premium_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # total USDT
    expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[OptionStatus] = mapped_column(
        str_enum(OptionStatus, "option_status"), nullable=False, default=OptionStatus.OPEN
    )
    payout: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    settle_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("strike > 0 AND size > 0 AND premium_paid >= 0", name="ck_options_positive"),
        Index("ix_options_open", "status", "expiry"),
        Index("ix_options_user", "user_id", "id"),
    )

    def intrinsic(self, mark: Decimal) -> Decimal:
        if self.type is OptionType.CALL:
            return max(Decimal(0), mark - self.strike) * self.size
        return max(Decimal(0), self.strike - mark) * self.size

    def __repr__(self) -> str:
        return f"<Option {self.type.value} {self.underlying} K={self.strike} x{self.size} {self.status.value}>"
