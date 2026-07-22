"""A mock custody provider for development.

It fakes the three things a real provider does — addresses, broadcasts, on-chain balance — without
keys, nodes, or a network. Deposits are injected through a dev endpoint rather than arriving from a
chain. Everything *around* custody (the deposit and withdrawal state machines, the ledger postings,
idempotency, reconciliation) is real, so replacing this with Fireblocks changes only this file.

Addresses and tx hashes are deterministic so the same input always yields the same value — a real
provider is not deterministic, but for a mock it makes tests and demos reproducible. They are
plausibly shaped per chain (0x… for EVM, T… for TRON) but are NOT valid addresses; nothing may
ever send real funds to them, which is the point of a testnet-first, account-gated rollout.
"""

import hashlib
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Asset,
    AssetNetwork,
    Chain,
    ChainFamily,
    Deposit,
    DepositStatus,
    Withdrawal,
    WithdrawalStatus,
)
from app.services.custody.base import CustodyProvider, DerivedAddress


def _digest(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


class MockCustodyProvider(CustodyProvider):
    def __init__(self, db_factory=None) -> None:
        # on_chain_balance needs to read deposits/withdrawals, so it is handed a session per call
        # via `bind_session`. A real provider would query the chain instead and need no DB.
        self._session: AsyncSession | None = None

    def bind_session(self, db: AsyncSession) -> "MockCustodyProvider":
        """Give the mock a session for its next `on_chain_balance` call.

        A real provider queries a node and needs no database; the mock derives "on-chain" holdings
        from our own credited-deposit and confirmed-withdrawal records, which is what makes
        reconciliation a genuine cross-check rather than a tautology — it compares the ledger's
        EXTERNAL balance against an independently-summed view of the same events.
        """
        self._session = db
        return self

    async def derive_address(self, user_id: int, chain: Chain) -> DerivedAddress:
        seed = _digest("addr", chain.code, user_id)
        if chain.family is ChainFamily.EVM:
            return DerivedAddress(address="0x" + seed[:40])
        if chain.family is ChainFamily.TRON:
            return DerivedAddress(address="T" + seed[:33])
        # Shared-memo chains: one address, per-user memo. None are seeded yet, but the branch is
        # here so adding one is not a special case later.
        if chain.address_model.value == "SHARED_MEMO":
            return DerivedAddress(address="SHARED-" + chain.code, memo=str(1_000_000 + user_id))
        return DerivedAddress(address=chain.code + "-" + seed[:32])

    async def sign_and_broadcast(
        self, *, chain: Chain, to_address: str, amount: Decimal, memo: str | None, reference: str
    ) -> str:
        # A real signer re-verifies everything and returns the chain's tx hash. The mock returns a
        # deterministic fake so a withdrawal record has a stable, inspectable hash.
        return "0x" + _digest("tx", chain.code, to_address, amount, reference)[:64]

    async def on_chain_balance(self, chain: Chain, symbol: str) -> Decimal:
        if self._session is None:
            raise RuntimeError("bind_session() must be called before on_chain_balance()")
        db = self._session

        network_id = (
            await db.execute(
                select(AssetNetwork.id)
                .join(Asset, Asset.id == AssetNetwork.asset_id)
                .where(AssetNetwork.chain_id == chain.id, Asset.symbol == symbol)
            )
        ).scalar_one_or_none()
        if network_id is None:
            return Decimal(0)

        credited = (
            await db.execute(
                select(func.coalesce(func.sum(Deposit.amount), 0)).where(
                    Deposit.asset_network_id == network_id,
                    Deposit.status == DepositStatus.CREDITED,
                )
            )
        ).scalar_one()
        withdrawn = (
            await db.execute(
                select(func.coalesce(func.sum(Withdrawal.amount), 0)).where(
                    Withdrawal.asset_network_id == network_id,
                    Withdrawal.status == WithdrawalStatus.CONFIRMED,
                )
            )
        ).scalar_one()
        return Decimal(credited) - Decimal(withdrawn)
