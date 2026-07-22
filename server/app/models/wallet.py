"""Deposit addresses, deposits, and withdrawals — the records that connect the ledger to a chain.

These are the state machines at the two edges of the wallet. The ledger is the source of truth
for balances; these tables are the source of truth for *what the chain did* and how each on-chain
event maps to a ledger transaction.

The single most important column in this file is `Deposit`'s unique `(asset_network_id, tx_hash,
vout)`. Webhooks retry and chains get re-scanned, so the same deposit is delivered more than once
— and a deposit credited twice is money handed out. The uniqueness constraint, not an `if exists`
check, is what makes crediting exactly-once.
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


class DepositStatus(str, enum.Enum):
    """DETECTED first (seen, not yet spendable), CREDITED once enough confirmations land.

    ORPHANED is the reorg case: a block we counted was replaced, so a deposit we saw is no longer
    on the canonical chain. If it had already been credited, the credit must be unwound — which is
    exactly where exchanges get robbed by deposit-then-reorg attacks.
    """

    DETECTED = "DETECTED"
    CREDITED = "CREDITED"
    ORPHANED = "ORPHANED"


class WithdrawalStatus(str, enum.Enum):
    """The accounting boundary is at reservation, not at broadcast.

    PENDING     — funds moved AVAILABLE -> PENDING_WITHDRAWAL; nothing on-chain yet.
    BROADCAST   — signed and sent; a tx hash exists but it is not final.
    CONFIRMED   — on-chain final; funds moved PENDING_WITHDRAWAL -> EXTERNAL, fee -> FEE_INCOME.
    FAILED      — broadcast failed or the tx was dropped; PENDING_WITHDRAWAL refunded to AVAILABLE.
    CANCELED    — cancelled before broadcast; refunded the same way.
    """

    PENDING = "PENDING"
    BROADCAST = "BROADCAST"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class DepositAddress(TimestampMixin, Base):
    """The address a user sends a given asset+network to.

    One per user per network. For PER_USER chains the address itself identifies the owner; for
    SHARED_MEMO chains (XRP, TON, XLM) the address is shared and `memo` identifies the user — which
    is why memo is stored here and why a memo-less deposit on such a chain cannot be attributed.
    """

    __tablename__ = "deposit_addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_network_id: Mapped[int] = mapped_column(
        ForeignKey("asset_networks.id", ondelete="RESTRICT"), nullable=False
    )

    address: Mapped[str] = mapped_column(String(128), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "asset_network_id", name="uq_deposit_addresses_user_network"),
        # A per-user address must be unique across the chain, or two users share a deposit route.
        Index("ix_deposit_addresses_lookup", "asset_network_id", "address"),
    )


class Deposit(TimestampMixin, Base):
    """One incoming on-chain transfer to one of our addresses."""

    __tablename__ = "deposits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    asset_network_id: Mapped[int] = mapped_column(
        ForeignKey("asset_networks.id", ondelete="RESTRICT"), nullable=False
    )
    deposit_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("deposit_addresses.id", ondelete="SET NULL"), nullable=True
    )

    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # An output index: one transaction can pay several addresses, so (tx_hash, vout) is the true
    # identity of a deposit, not tx_hash alone.
    vout: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    status: Mapped[DepositStatus] = mapped_column(
        str_enum(DepositStatus, "deposit_status"), nullable=False, default=DepositStatus.DETECTED
    )
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_confirmations: Mapped[int] = mapped_column(Integer, nullable=False)

    # Tracked so a reorg is detectable: if the block at this height later has a different hash,
    # every deposit from the orphaned block is suspect.
    block_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # The ledger transaction that credited this deposit. NULL until CREDITED. The link is what lets
    # reconciliation check that every credited deposit actually moved the ledger.
    ledger_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        # Exactly-once. This constraint, not application logic, is what stops a double credit.
        UniqueConstraint("asset_network_id", "tx_hash", "vout", name="uq_deposits_txid"),
        CheckConstraint("amount > 0", name="ck_deposits_amount_positive"),
        Index("ix_deposits_user", "user_id", "id"),
        Index("ix_deposits_status", "status"),
    )


class Withdrawal(TimestampMixin, Base):
    """One outgoing transfer requested by a user."""

    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    asset_network_id: Mapped[int] = mapped_column(
        ForeignKey("asset_networks.id", ondelete="RESTRICT"), nullable=False
    )

    to_address: Mapped[str] = mapped_column(String(128), nullable=False)
    memo: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # amount is what the user receives; fee is what we charge on top. Both leave AVAILABLE
    # together (amount + fee reserved), amount goes to EXTERNAL, fee to FEE_INCOME.
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    status: Mapped[WithdrawalStatus] = mapped_column(
        str_enum(WithdrawalStatus, "withdrawal_status"),
        nullable=False,
        default=WithdrawalStatus.PENDING,
    )
    tx_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The two ledger transactions: the reserve (AVAILABLE -> PENDING_WITHDRAWAL) and the settle or
    # refund. Kept so the full accounting of a withdrawal is reconstructible.
    reserve_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=True
    )
    settle_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=True
    )

    # Client-supplied dedup key so a double-submit (user double-clicks, network retry) does not
    # create two withdrawals. Optional; when present it is unique.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0 AND fee >= 0", name="ck_withdrawals_amounts"),
        UniqueConstraint("idempotency_key", name="uq_withdrawals_idempotency_key"),
        Index("ix_withdrawals_user", "user_id", "id"),
        Index("ix_withdrawals_status", "status"),
    )
