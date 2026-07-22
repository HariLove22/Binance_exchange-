"""Double-entry ledger.

Three tables, and one invariant that must never break:

    SELECT asset, SUM(amount) FROM ledger_entries GROUP BY asset   -->  0, always.

A non-zero sum means money was created or destroyed. Entries are append-only — there is no
UPDATE and no DELETE; a mistake is fixed with a compensating transaction, never an edit.

`accounts.balance` is a cached running total of that account's entries. It exists so reads are
one row instead of an aggregate; the entries remain the source of truth.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Account types. User-owned: AVAILABLE (spendable), LOCKED (reserved by open orders).
# System-owned (user_id IS NULL): EXTERNAL is the outside world — deposits flow in from it,
# so its balance goes negative by exactly what the system holds. FEE_INCOME collects fees.
AVAILABLE = "AVAILABLE"
LOCKED = "LOCKED"
EXTERNAL = "EXTERNAL"
FEE_INCOME = "FEE_INCOME"

USER_ACCOUNT_TYPES = (AVAILABLE, LOCKED)
SYSTEM_ACCOUNT_TYPES = (EXTERNAL, FEE_INCOME)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL for system accounts (EXTERNAL, FEE_INCOME).
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    asset: Mapped[str] = mapped_column(String(10), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Integer count of the asset's minimum unit. Never a float.
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "asset", "account_type", name="uq_account_user_asset_type"),
        # Postgres treats NULLs as distinct, so the constraint above does not stop duplicate
        # system rows. This partial index does.
        Index(
            "uq_account_system",
            "asset",
            "account_type",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        who = f"user={self.user_id}" if self.user_id else "system"
        return f"<Account {who} {self.asset}/{self.account_type} bal={self.balance}>"


class Transaction(Base):
    """A group of entries that must balance to zero per asset."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # The UNIQUE constraint is what makes retries safe — it *is* exactly-once delivery.
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # FAUCET | TRADE | LOCK | ...
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    asset: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # Signed: debit is negative, credit positive. Zero is meaningless, so it's rejected.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint("amount <> 0", name="ck_entry_amount_nonzero"),)
