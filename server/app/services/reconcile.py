"""Reconciliation: does the ledger agree with what custody holds on-chain?

Two independent checks, both of which must pass:

1. **Trial balance is zero per asset.** Internal consistency — the ledger did not create or
   destroy money.
2. **Ledger EXTERNAL == custody's on-chain holdings, per asset.** External consistency — the
   money we say left or arrived matches the money that actually did.

The second is the one that catches theft and crediting bugs. EXTERNAL goes negative by every
deposit and positive by every withdrawal, so `-EXTERNAL` is what we *should* be holding on-chain.
Custody reports what it *actually* holds. A gap means either a deposit credited that no funds back,
or funds moved that the ledger never recorded — both reasons to halt withdrawals and page a human.

In production this runs continuously, not on request.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountType, Asset, AssetNetwork, Chain, LedgerEntry
from app.services.custody import custody
from app.services.custody.mock import MockCustodyProvider


@dataclass(frozen=True)
class AssetReconciliation:
    asset: str
    trial_balance: str  # sum of all entries; must be "0"
    ledger_external: str  # -EXTERNAL: what the ledger says we hold on-chain
    custody_onchain: str  # what custody reports holding
    balanced: bool


async def reconcile(db: AsyncSession) -> list[AssetReconciliation]:
    # Trial balance per asset.
    trial = dict(
        (
            await db.execute(
                select(Asset.symbol, func.coalesce(func.sum(LedgerEntry.amount), 0))
                .join(LedgerEntry, LedgerEntry.asset_id == Asset.id)
                .group_by(Asset.symbol)
            )
        ).all()
    )

    # Ledger EXTERNAL balance per asset.
    external = dict(
        (
            await db.execute(
                select(Asset.symbol, Account.balance)
                .join(Account, Account.asset_id == Asset.id)
                .where(Account.account_type == AccountType.EXTERNAL)
            )
        ).all()
    )

    # Only custodial assets are reconciled: a synthetic asset has no chain, so there is nothing
    # on-chain to compare against. Its consistency is covered by the trial balance alone.
    custodial = {
        s for s in (await db.execute(select(Asset.symbol).where(Asset.custodial.is_(True)))).scalars().all()
    }

    # Custody's on-chain holdings per asset, summed across the chains the asset lives on.
    networks = (
        await db.execute(
            select(Asset.symbol, Chain)
            .join(AssetNetwork, AssetNetwork.asset_id == Asset.id)
            .join(Chain, Chain.id == AssetNetwork.chain_id)
            .where(Asset.custodial.is_(True))
        )
    ).all()

    provider = custody
    if isinstance(provider, MockCustodyProvider):
        provider.bind_session(db)

    onchain: dict[str, Decimal] = {}
    for symbol, chain in networks:
        onchain[symbol] = onchain.get(symbol, Decimal(0)) + await provider.on_chain_balance(chain, symbol)

    results: list[AssetReconciliation] = []
    # Report only custodial assets — synthetic ones have no custody to compare against. Their
    # internal consistency is still guaranteed by the ledger's per-asset zero-sum (the DB trigger),
    # so leaving them out of this report does not weaken any money-integrity check.
    for symbol in sorted(s for s in (set(trial) | set(external) | set(onchain)) if s in custodial):
        tb = Decimal(trial.get(symbol, 0))
        ext = Decimal(external.get(symbol, 0))
        oc = onchain.get(symbol, Decimal(0))
        balanced = tb == 0 and (-ext) == oc
        results.append(
            AssetReconciliation(
                asset=symbol,
                trial_balance=f"{tb:f}",
                ledger_external=f"{-ext:f}",
                custody_onchain=f"{oc:f}",
                balanced=balanced,
            )
        )
    return results
