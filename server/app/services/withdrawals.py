"""Withdrawal flow: request -> reserve -> broadcast -> confirm (or refund).

The accounting boundary is at reservation, not at broadcast: the moment a user requests, the funds
leave AVAILABLE for PENDING_WITHDRAWAL, so they cannot be double-spent while the transaction is in
flight. They only cross into EXTERNAL — actually leaving the system — once the chain confirms. A
broadcast that fails refunds from PENDING_WITHDRAWAL without anything having been invented.

Real withdrawals gate on 2FA, email confirmation, address whitelisting with a time-lock, and a
risk screen. Kamni's base has none of those yet, so this enforces the balance and state machine and
leaves those gates as explicit TODOs rather than pretending they exist.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Asset,
    AssetNetwork,
    Chain,
    Withdrawal,
    WithdrawalStatus,
)
from app.services import ledger
from app.services.custody import custody
from app.services.ledger import InsufficientFunds


class WithdrawalError(Exception):
    """A withdrawal operation was refused. Safe to surface."""


async def request_withdrawal(
    db: AsyncSession,
    *,
    user_id: int,
    asset_network_id: int,
    to_address: str,
    amount: Decimal,
    memo: str | None = None,
    idempotency_key: str | None = None,
) -> Withdrawal:
    """Validate, reserve funds, and broadcast. Returns a BROADCAST (or PENDING) withdrawal.

    Reserve-then-broadcast, never the reverse: if we broadcast first and the reserve failed, funds
    would have left the chain that the ledger never debited.
    """
    network = (
        await db.execute(
            select(AssetNetwork)
            .options(selectinload(AssetNetwork.asset), selectinload(AssetNetwork.chain))
            .where(AssetNetwork.id == asset_network_id)
        )
    ).scalar_one_or_none()
    if network is None:
        raise WithdrawalError("unknown asset network")
    if not network.asset.custodial:
        # Synthetic assets never touch a chain — they can only be sold back for USDT, not sent out.
        raise WithdrawalError(f"{network.asset.symbol} is a synthetic asset and cannot be withdrawn")
    if not network.withdraw_enabled:
        raise WithdrawalError("withdrawals are disabled for this network")
    if amount <= 0:
        raise WithdrawalError("amount must be positive")
    if amount < network.min_withdrawal:
        raise WithdrawalError(f"below minimum withdrawal of {network.min_withdrawal}")
    if amount.as_tuple().exponent < -network.asset.scale:
        raise WithdrawalError(f"more precision than {network.asset.symbol} allows")

    # Dedup a double-submit before doing any work.
    if idempotency_key is not None:
        prior = (
            await db.execute(select(Withdrawal).where(Withdrawal.idempotency_key == idempotency_key))
        ).scalar_one_or_none()
        if prior is not None:
            return prior

    fee = network.withdrawal_fee
    total = amount + fee

    withdrawal = Withdrawal(
        user_id=user_id,
        asset_network_id=asset_network_id,
        to_address=to_address,
        memo=memo,
        amount=amount,
        fee=fee,
        status=WithdrawalStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    db.add(withdrawal)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        # Raced on the idempotency key; the other request won.
        return (
            await db.execute(select(Withdrawal).where(Withdrawal.idempotency_key == idempotency_key))
        ).scalar_one()

    # Reserve: AVAILABLE -> PENDING_WITHDRAWAL. Keyed on the withdrawal id so it is idempotent.
    try:
        reserve = await ledger.reserve_withdrawal(
            db,
            user_id=user_id,
            asset_id=network.asset_id,
            total=total,
            idempotency_key=f"withdrawal-reserve:{withdrawal.id}",
            reference=f"withdrawal={withdrawal.id}",
        )
    except InsufficientFunds as exc:
        raise WithdrawalError(str(exc)) from exc
    if reserve is not None:
        withdrawal.reserve_txn_id = reserve.id

    # Broadcast through custody. A real signer re-verifies destination and limits here.
    tx_hash = await custody.sign_and_broadcast(
        chain=network.chain,
        to_address=to_address,
        amount=amount,
        memo=memo,
        reference=f"withdrawal={withdrawal.id}",
    )
    withdrawal.tx_hash = tx_hash
    withdrawal.status = WithdrawalStatus.BROADCAST
    await db.flush()
    return withdrawal


async def confirm_withdrawal(db: AsyncSession, withdrawal: Withdrawal) -> Withdrawal:
    """Mark a broadcast withdrawal final: PENDING_WITHDRAWAL -> EXTERNAL, fee -> FEE_INCOME."""
    if withdrawal.status is WithdrawalStatus.CONFIRMED:
        return withdrawal
    if withdrawal.status is not WithdrawalStatus.BROADCAST:
        raise WithdrawalError(f"cannot confirm a withdrawal in status {withdrawal.status.value}")

    network = await db.get(AssetNetwork, withdrawal.asset_network_id)
    settle = await ledger.settle_withdrawal(
        db,
        user_id=withdrawal.user_id,
        asset_id=network.asset_id,
        amount=withdrawal.amount,
        fee=withdrawal.fee,
        idempotency_key=f"withdrawal-settle:{withdrawal.id}",
        reference=f"withdrawal={withdrawal.id}",
    )
    if settle is not None:
        withdrawal.settle_txn_id = settle.id
    withdrawal.status = WithdrawalStatus.CONFIRMED
    return withdrawal


async def fail_withdrawal(db: AsyncSession, withdrawal: Withdrawal, reason: str) -> Withdrawal:
    """A broadcast that never confirmed, or a cancel before broadcast: refund to AVAILABLE."""
    if withdrawal.status in {WithdrawalStatus.FAILED, WithdrawalStatus.CANCELED}:
        return withdrawal
    if withdrawal.status is WithdrawalStatus.CONFIRMED:
        raise WithdrawalError("cannot fail a confirmed withdrawal")

    network = await db.get(AssetNetwork, withdrawal.asset_network_id)
    refund = await ledger.refund_withdrawal(
        db,
        user_id=withdrawal.user_id,
        asset_id=network.asset_id,
        total=withdrawal.amount + withdrawal.fee,
        idempotency_key=f"withdrawal-refund:{withdrawal.id}",
        reference=f"withdrawal={withdrawal.id}",
    )
    if refund is not None:
        withdrawal.settle_txn_id = refund.id
    withdrawal.status = (
        WithdrawalStatus.CANCELED if withdrawal.status is WithdrawalStatus.PENDING else WithdrawalStatus.FAILED
    )
    withdrawal.failure_reason = reason
    return withdrawal


@dataclass(frozen=True)
class WithdrawalView:
    id: int
    asset: str
    chain: str
    to_address: str
    amount: str
    fee: str
    status: str
    tx_hash: str | None


async def list_withdrawals(db: AsyncSession, user_id: int, limit: int = 50) -> list[WithdrawalView]:
    rows = (
        await db.execute(
            select(Withdrawal, Asset.symbol, Asset.scale, Chain.code)
            .join(AssetNetwork, AssetNetwork.id == Withdrawal.asset_network_id)
            .join(Asset, Asset.id == AssetNetwork.asset_id)
            .join(Chain, Chain.id == AssetNetwork.chain_id)
            .where(Withdrawal.user_id == user_id)
            .order_by(Withdrawal.id.desc())
            .limit(limit)
        )
    ).all()

    def fmt(v: Decimal, scale: int) -> str:
        return f"{v.quantize(Decimal(1).scaleb(-scale)):f}"

    return [
        WithdrawalView(
            id=w.id,
            asset=symbol,
            chain=chain,
            to_address=w.to_address,
            amount=fmt(w.amount, scale),
            fee=fmt(w.fee, scale),
            status=w.status.value,
            tx_hash=w.tx_hash,
        )
        for w, symbol, scale, chain in rows
    ]
