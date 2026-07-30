"""Rewards Hub: one row per reward a user has claimed, so a task pays out exactly once.

Tasks themselves live in code (services/rewards.py) — their conditions are checked against real state
(KYC approved, first trade, funded, referred a friend, opened margin). This table only records the
claim, keyed uniquely on (user, task), which is what prevents a second payout.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import MONEY


class RewardClaim(Base):
    __tablename__ = "reward_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(40), nullable=False)
    reward_usdt: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "task_id", name="uq_reward_claims_user_task"),)

    def __repr__(self) -> str:
        return f"<RewardClaim user={self.user_id} task={self.task_id}>"
