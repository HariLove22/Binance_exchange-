"""Referrals: who invited whom, and the commission a referrer earns from their referees' fees.

One row per referred user (a user has exactly one referrer, set at sign-up and never changed). The
referrer earns a cut of the trading fees their referees pay — credited from FEE_INCOME so it is real
money out of the exchange's revenue, and the trial balance stays at zero.
"""

from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.core.db import Base
from app.models.asset import MONEY


class Referral(Base):
    """A referrer -> referee link. `referee_id` is unique: you can only be referred once."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    referee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True)

    # Running total of commission paid to the referrer from this referee's fees, valued in USD at
    # payout time. Display-only; the actual funds are in the referrer's balances.
    earned_usd: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("referee_id", name="uq_referrals_referee"),)

    def __repr__(self) -> str:
        return f"<Referral {self.referrer_id} -> {self.referee_id}>"
