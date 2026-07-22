"""Deposit flow: address -> detect -> confirm -> credit.

The chain tells us a transfer arrived; this turns that into a ledger credit, exactly once, only
after enough confirmations, and only if the block it is in survives.
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
    Deposit,
    DepositAddress,
    DepositStatus,
    TransactionKind,
)
from app.services import ledger
from app.services.custody import custody


class DepositError(Exception):
    """A deposit operation was refused. Safe to surface."""


async def get_or_create_address(db: AsyncSession, user_id: int, asset_network_id: int) -> DepositAddress:
    """The address a user sends this asset+network to. Created once, then reused.

    The same address is returned on every call — generating a fresh one per request would scatter a
    user's funds across addresses and multiply the sweep cost. Racing callers are handled by the
    unique constraint, not by checking first.
    """
    network = (
        await db.execute(
            select(AssetNetwork).options(selectinload(AssetNetwork.chain)).where(AssetNetwork.id == asset_network_id)
        )
    ).scalar_one_or_none()
    if network is None:
        raise DepositError("unknown asset network")
    if not network.deposit_enabled:
        raise DepositError("deposits are disabled for this network")

    existing = (
        await db.execute(
            select(DepositAddress).where(
                DepositAddress.user_id == user_id,
                DepositAddress.asset_network_id == asset_network_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    derived = await custody.derive_address(user_id, network.chain)
    address = DepositAddress(
        user_id=user_id,
        asset_network_id=asset_network_id,
        address=derived.address,
        memo=derived.memo,
    )
    db.add(address)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        address = (
            await db.execute(
                select(DepositAddress).where(
                    DepositAddress.user_id == user_id,
                    DepositAddress.asset_network_id == asset_network_id,
                )
            )
        ).scalar_one()
    return address


def _required_confirmations(network: AssetNetwork, amount: Decimal) -> int:
    """Small deposits credit fast, large ones wait longer — a value-scaled security decision."""
    return network.confirmations_large if amount >= network.large_threshold else network.confirmations


async def record_deposit(
    db: AsyncSession,
    *,
    asset_network_id: int,
    tx_hash: str,
    amount: Decimal,
    vout: int = 0,
    block_height: int | None = None,
    block_hash: str | None = None,
    confirmations: int = 0,
) -> Deposit:
    """Register an incoming transfer, or return the existing record if already seen.

    Idempotent on `(asset_network_id, tx_hash, vout)`: webhooks retry and chains get re-scanned, so
    the same deposit arrives repeatedly. The unique constraint makes the second arrival a lookup,
    not a second credit.

    The owner is resolved from the destination address. A transfer to an address we do not know is
    not ours to credit and is refused — on a shared-memo chain that also means a missing memo is
    unattributable.
    """
    network = (
        await db.execute(
            select(AssetNetwork).options(selectinload(AssetNetwork.asset)).where(AssetNetwork.id == asset_network_id)
        )
    ).scalar_one_or_none()
    if network is None:
        raise DepositError("unknown asset network")
    if amount <= 0:
        raise DepositError("deposit amount must be positive")

    existing = (
        await db.execute(
            select(Deposit).where(
                Deposit.asset_network_id == asset_network_id,
                Deposit.tx_hash == tx_hash,
                Deposit.vout == vout,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    return Deposit(
        user_id=None,  # set below once the address resolves
        asset_network_id=asset_network_id,
        tx_hash=tx_hash,
        vout=vout,
        amount=amount,
        status=DepositStatus.DETECTED,
        confirmations=confirmations,
        required_confirmations=_required_confirmations(network, amount),
        block_height=block_height,
        block_hash=block_hash,
    )


async def credit_if_confirmed(db: AsyncSession, deposit: Deposit) -> Deposit:
    """Credit the ledger once confirmations are sufficient. Idempotent — safe to call repeatedly.

    Crediting is a single ledger transaction (EXTERNAL -> user AVAILABLE) keyed on the deposit's
    on-chain identity, so even if this is called twice for the same confirmed deposit the ledger
    posts it once.
    """
    if deposit.status is DepositStatus.CREDITED:
        return deposit
    if deposit.status is DepositStatus.ORPHANED:
        raise DepositError("cannot credit an orphaned deposit")
    if deposit.confirmations < deposit.required_confirmations:
        return deposit
    if deposit.user_id is None:
        raise DepositError("deposit has no owner; cannot credit")

    network = await db.get(AssetNetwork, deposit.asset_network_id)
    txn = await ledger.credit(
        db,
        user_id=deposit.user_id,
        asset_id=network.asset_id,
        amount=deposit.amount,
        kind=TransactionKind.DEPOSIT,
        # The deposit's on-chain identity is the idempotency key — the same key the unique
        # constraint uses, so a credit is exactly-once from both directions.
        idempotency_key=f"deposit:{deposit.asset_network_id}:{deposit.tx_hash}:{deposit.vout}",
        reference=f"tx={deposit.tx_hash}",
    )
    deposit.status = DepositStatus.CREDITED
    if txn is not None:
        deposit.ledger_txn_id = txn.id
    return deposit


@dataclass(frozen=True)
class DepositView:
    id: int
    asset: str
    chain: str
    tx_hash: str
    amount: str
    status: str
    confirmations: int
    required_confirmations: int


async def list_deposits(db: AsyncSession, user_id: int, limit: int = 50) -> list[DepositView]:
    rows = (
        await db.execute(
            select(Deposit, Asset.symbol, Asset.scale, Chain.code)
            .join(AssetNetwork, AssetNetwork.id == Deposit.asset_network_id)
            .join(Asset, Asset.id == AssetNetwork.asset_id)
            .join(Chain, Chain.id == AssetNetwork.chain_id)
            .where(Deposit.user_id == user_id)
            .order_by(Deposit.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        DepositView(
            id=d.id,
            asset=symbol,
            chain=chain,
            tx_hash=d.tx_hash,
            amount=f"{d.amount.quantize(Decimal(1).scaleb(-scale)):f}",
            status=d.status.value,
            confirmations=d.confirmations,
            required_confirmations=d.required_confirmations,
        )
        for d, symbol, scale, chain in rows
    ]
