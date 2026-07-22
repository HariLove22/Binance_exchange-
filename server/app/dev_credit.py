"""Fund a user with test money — development only, through the real deposit flow.

    python -m app.dev_credit <email> <asset> <amount> [chain]
    python -m app.dev_credit wallet-demo@example.com USDT 5000
    python -m app.dev_credit wallet-demo@example.com USDT 5000 TRON

This does NOT mint a raw ledger credit. It simulates an on-chain deposit end to end: derive an
address, record the deposit, confirm it, credit the ledger. That matters because reconciliation
compares the ledger's EXTERNAL balance against custody's on-chain holdings — a raw credit with no
deposit behind it would (correctly) show up as unbacked and break reconciliation. Funds created
here are backed, so reconciliation stays green.

Refuses to run outside development.
"""

import asyncio
import sys
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models import Asset, AssetNetwork, Chain, User
from app.services import deposits as deposit_service


async def main(email: str, symbol: str, amount_str: str, chain_code: str | None) -> int:
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        print(f"refusing: environment is {settings.environment!r}, not development")
        return 2

    try:
        amount = Decimal(amount_str)
    except InvalidOperation:
        print(f"not a valid amount: {amount_str!r}")
        return 2
    if amount <= 0:
        print("amount must be positive")
        return 2

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
        if user is None:
            print(f"no user with email {email!r}")
            return 1

        # Pick the network: the named chain, or the first one this asset lives on.
        query = (
            select(AssetNetwork)
            .join(Asset, Asset.id == AssetNetwork.asset_id)
            .where(Asset.symbol == symbol.upper())
        )
        if chain_code:
            query = query.join(Chain, Chain.id == AssetNetwork.chain_id).where(Chain.code == chain_code.upper())
        network = (await db.execute(query.order_by(AssetNetwork.id))).scalars().first()
        if network is None:
            print(f"no network for {symbol!r}" + (f" on {chain_code}" if chain_code else ""))
            return 1

        # The seeder ships networks disabled; enable this one for the deposit (dev only).
        if not network.deposit_enabled:
            network.deposit_enabled = True
            await db.flush()

        address = await deposit_service.get_or_create_address(db, user.id, network.id)

        import time

        tx_hash = f"0xdev{user.id}{int(time.time() * 1000)}"
        deposit = await deposit_service.record_deposit(
            db, asset_network_id=network.id, tx_hash=tx_hash, amount=amount
        )
        deposit.user_id = user.id
        deposit.deposit_address_id = address.id
        deposit.confirmations = deposit.required_confirmations
        db.add(deposit)
        await db.flush()
        await deposit_service.credit_if_confirmed(db, deposit)
        await db.commit()

        print(f"credited {amount} {symbol.upper()} to {email} via deposit {deposit.id} "
              f"(backed, reconciliation stays balanced)")
        return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        raise SystemExit(2)
    chain = sys.argv[4] if len(sys.argv) == 5 else None
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3], chain)))
