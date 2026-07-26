"""The double-entry ledger. Every balance in the exchange is derived from this.

Read this before touching anything that moves money.

**A balance is not a column.** It is the sum of the entries against an account. The temptation is
a mutable `balance` you UPDATE — and it works until one balance is wrong and there is no way to
learn why, when, or by how much. Entries make a balance reconstructible, which is the difference
between an incident you resolve and one you only apologise for. We keep a cached balance for read
speed, updated in the same transaction as its entries so the two can never disagree.

**Every transaction sums to zero, per asset.** Money is never created or destroyed, only moved.
If a transaction does not balance, we invented money — and the check that catches it lives in the
database, not in a code review.

**Entries are append-only.** No UPDATE, no DELETE. Corrections are compensating transactions, so
the history shows both the error and the fix.

The `EXTERNAL` account makes deposits and withdrawals balance: a deposit is a transfer from the
outside world into the user, so EXTERNAL goes negative. Its magnitude mirrors on-chain holdings,
and reconciling the two is how theft and bugs are found.

Spot only for now. Funding / Margin sub-wallets are added later via a `wallet` column — additive,
not a rewrite. Nothing here assumes Spot is the only wallet that will exist.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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


class AccountType(str, enum.Enum):
    """What an account is for.

    User-owned:
      AVAILABLE           — spendable.
      LOCKED              — reserved against an open order.
      PENDING_WITHDRAWAL  — reserved for a withdrawal in flight: debited from AVAILABLE when the
                            withdrawal is requested, and only leaves for EXTERNAL once the on-chain
                            transaction confirms. Still the user's money until then, so a failed
                            broadcast can refund it without inventing anything.
    System-owned (user_id NULL):
      EXTERNAL     — the outside world; deposits come from it, withdrawals go to it.
      FEE_INCOME   — fees we have earned.
      TDS_PAYABLE  — 1% withheld on VDA transfers under Indian rules, owed onward. Not revenue —
                     it passes through us. Present from the start so it is never a retrofit.
    """

    AVAILABLE = "AVAILABLE"
    LOCKED = "LOCKED"
    PENDING_WITHDRAWAL = "PENDING_WITHDRAWAL"
    EXTERNAL = "EXTERNAL"
    FEE_INCOME = "FEE_INCOME"
    TDS_PAYABLE = "TDS_PAYABLE"


USER_ACCOUNT_TYPES = frozenset(
    {AccountType.AVAILABLE, AccountType.LOCKED, AccountType.PENDING_WITHDRAWAL}
)
# May legitimately go negative. EXTERNAL is negative by construction; TDS accrues as a liability.
NEGATIVE_ALLOWED = frozenset({AccountType.EXTERNAL, AccountType.TDS_PAYABLE})


class TransactionKind(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ORDER_LOCK = "ORDER_LOCK"
    ORDER_UNLOCK = "ORDER_UNLOCK"
    TRADE = "TRADE"
    FEE = "FEE"
    TDS = "TDS"
    ADJUSTMENT = "ADJUSTMENT"
    # Test funds credited by an admin — a distinct kind so it is never mistaken for a real
    # deposit in reporting and every one is trivially findable.
    ADMIN_CREDIT = "ADMIN_CREDIT"


class Account(TimestampMixin, Base):
    """A bucket entries are written against. `balance` is a cache; entries are truth."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # NULL for system accounts. One FEE_INCOME per asset, not one per user — enforced by the
    # partial unique indexes below.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(str_enum(AccountType, "account_type"), nullable=False)

    balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    entries: Mapped[list["LedgerEntry"]] = relationship(back_populates="account")

    __table_args__ = (
        # One account per (user, asset, type) — a second AVAILABLE in the same asset would let a
        # race double-spend across the two.
        Index(
            "uq_accounts_user_asset_type",
            "user_id",
            "asset_id",
            "account_type",
            unique=True,
            postgresql_where=user_id.isnot(None),
        ),
        # One system account per (asset, type).
        Index(
            "uq_accounts_system_asset_type",
            "asset_id",
            "account_type",
            unique=True,
            postgresql_where=user_id.is_(None),
        ),
        # A user account must have an owner; a system account must not. Mixing them means fees
        # credited to a user, or a balance nobody owns.
        CheckConstraint(
            "(account_type IN ('AVAILABLE', 'LOCKED', 'PENDING_WITHDRAWAL') AND user_id IS NOT NULL)"
            " OR (account_type NOT IN ('AVAILABLE', 'LOCKED', 'PENDING_WITHDRAWAL') AND user_id IS NULL)",
            name="ck_accounts_user_type_consistency",
        ),
        # A negative user balance means we let someone spend money they did not have.
        CheckConstraint(
            "balance >= 0 OR account_type IN ('EXTERNAL', 'TDS_PAYABLE')",
            name="ck_accounts_no_negative_user_balance",
        ),
    )

    def __repr__(self) -> str:
        return f"<Account {self.account_type.value} user={self.user_id} asset={self.asset_id}>"


class LedgerTransaction(TimestampMixin, Base):
    """A group of entries that must balance to zero, per asset.

    `idempotency_key` is exactly-once as a UNIQUE constraint, not a check-then-insert — the latter
    loses the race. Webhooks retry, clients retry, queues redeliver; a double credit has to fail
    in the database, not in an `if`.
    """

    __tablename__ = "ledger_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    kind: Mapped[TransactionKind] = mapped_column(str_enum(TransactionKind, "transaction_kind"), nullable=False)

    # Free-form provenance: a tx hash, an order id, an admin's user id.
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)

    entries: Mapped[list["LedgerEntry"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_ledger_transactions_kind", "kind", "created_at"),)

    def __repr__(self) -> str:
        return f"<LedgerTransaction {self.kind.value} {self.idempotency_key}>"


class LedgerEntry(Base):
    """One movement against one account. Immutable. Positive credits, negative debits."""

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    # Denormalised from the account so the trial balance groups by asset without a join — that
    # reconciliation query runs constantly.
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)

    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    transaction: Mapped["LedgerTransaction"] = relationship(back_populates="entries")
    account: Mapped["Account"] = relationship(back_populates="entries")

    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_ledger_entries_nonzero"),
        Index("ix_ledger_entries_account", "account_id", "id"),
        Index("ix_ledger_entries_transaction", "transaction_id"),
        # One account at most once per transaction — two entries for the same account is a caller
        # bug, and collapsing keeps the per-transaction balance check simple.
        UniqueConstraint("transaction_id", "account_id", name="uq_ledger_entries_txn_account"),
    )

    def __repr__(self) -> str:
        return f"<LedgerEntry account={self.account_id} amount={self.amount}>"
