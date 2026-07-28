"""Margin trading: leveraged accounts and the loans that fund them.

Margin lets a user trade with borrowed funds. It reuses the same double-entry ledger and (later) the
same matching engine as spot — the difference is a separate MARGIN sub-wallet, borrowed liquidity,
hourly interest, and forced liquidation when equity gets too thin. Spot funds are never at risk from
a margin position; the wallets are distinct accounts.

A **cross** account shares one collateral pool across all pairs (one account per user). An
**isolated** account rings a single pair's collateral and risk off from everything else (one account
per user+symbol). New accounts default to cross.
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import MONEY, TimestampMixin, str_enum


class MarginMode(str, enum.Enum):
    CROSS = "CROSS"        # one shared collateral pool across all pairs
    ISOLATED = "ISOLATED"  # collateral and risk ring-fenced per pair


class MarginTier(str, enum.Enum):
    """Cross-margin tiers, gating the leverage ceiling. Isolated leverage is set per pair instead."""

    CLASSIC = "CLASSIC"  # up to 3x
    PRO = "PRO"          # up to 10x (up to 20x for eligible accounts)


class MarginAccountStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MarginLoanStatus(str, enum.Enum):
    OPEN = "OPEN"
    REPAID = "REPAID"


class MarginAccount(TimestampMixin, Base):
    """A user's margin account. Cross: symbol is NULL (one per user). Isolated: one per user+symbol."""

    __tablename__ = "margin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    mode: Mapped[MarginMode] = mapped_column(str_enum(MarginMode, "margin_mode"), nullable=False)
    # NULL for cross (spans every pair); the pair symbol for isolated.
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)

    tier: Mapped[MarginTier] = mapped_column(
        str_enum(MarginTier, "margin_tier"), nullable=False, default=MarginTier.CLASSIC
    )
    # The account's leverage ceiling. Configurable within what the tier / pair allows.
    max_leverage: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("3"))

    status: Mapped[MarginAccountStatus] = mapped_column(
        str_enum(MarginAccountStatus, "margin_account_status"), nullable=False, default=MarginAccountStatus.ACTIVE
    )

    __table_args__ = (
        CheckConstraint("max_leverage >= 1", name="ck_margin_accounts_leverage"),
        # Cross has no symbol; isolated must have one.
        CheckConstraint(
            "(mode = 'CROSS' AND symbol IS NULL) OR (mode = 'ISOLATED' AND symbol IS NOT NULL)",
            name="ck_margin_accounts_symbol_by_mode",
        ),
        # One cross account per user; one isolated account per user+symbol. A partial unique index
        # per branch keeps both rules in the database.
        Index("uq_margin_cross", "user_id", unique=True, postgresql_where=(mode == MarginMode.CROSS)),
        Index("uq_margin_isolated", "user_id", "symbol", unique=True,
              postgresql_where=(mode == MarginMode.ISOLATED)),
    )

    @property
    def wallet(self) -> str:
        """The ledger sub-wallet backing this account: MARGIN (cross) or MARGIN:{symbol} (isolated)."""
        return "MARGIN" if self.symbol is None else f"MARGIN:{self.symbol.upper()}"

    def __repr__(self) -> str:
        return f"<MarginAccount {self.mode.value} user={self.user_id} symbol={self.symbol} {self.max_leverage}x>"


class MarginLoan(TimestampMixin, Base):
    """One borrow against a margin account. Principal is what is still owed; interest accrues hourly.

    A loan opens when funds are borrowed and closes when principal and accrued interest are fully
    repaid. The pool (MARGIN_BORROWED) mirrors the principal; interest becomes fee income on repay.
    """

    __tablename__ = "margin_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    margin_account_id: Mapped[int] = mapped_column(
        ForeignKey("margin_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)

    principal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    accrued_interest: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    hourly_rate: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    status: Mapped[MarginLoanStatus] = mapped_column(
        str_enum(MarginLoanStatus, "margin_loan_status"), nullable=False, default=MarginLoanStatus.OPEN
    )
    # When interest was last folded in — accrual advances this forward, whole hours at a time.
    last_accrued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("principal >= 0 AND accrued_interest >= 0 AND hourly_rate >= 0",
                        name="ck_margin_loans_nonneg"),
        Index("ix_margin_loans_account", "margin_account_id", "status"),
        Index("ix_margin_loans_open", "status", "asset_id"),
    )

    @property
    def owed(self) -> Decimal:
        return self.principal + self.accrued_interest

    def __repr__(self) -> str:
        return f"<MarginLoan acct={self.margin_account_id} asset={self.asset_id} owed={self.owed} {self.status.value}>"
