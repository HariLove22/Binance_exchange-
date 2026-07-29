"""Dev-only: credit test funds to a user through the real deposit flow.

A balance in this project is NOT a column you can UPSERT — it is the sum of ledger entries, and a
DB constraint forces every transaction to net to zero per asset (see app/models/ledger.py). Writing
a `balances` row directly would either trip that constraint or desync the cached balance from the
entries, quietly corrupting every later trade.

So this reuses the exact path app/api/routes/admin.py::credit_user takes — get_or_create_address ->
record_deposit -> credit_if_confirmed -> ledger.credit — which posts a correct, exactly-once,
zero-sum DEPOSIT transaction and keeps reconciliation balanced.

Usage (from server/, venv active):
    python scripts/fund_user.py 1 BTC 5
    python scripts/fund_user.py 1 USDT 100000
"""

import asyncio
import selectors
import sys
import time
from decimal import Decimal
from pathlib import Path

# Run from anywhere: make `app` importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    # psycopg async cannot use the default ProactorEventLoop. Match run.py.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select  # noqa: E402

from app.core.db import AsyncSessionLocal  # noqa: E402
from app.models import Asset, AssetNetwork, User  # noqa: E402
from app.services import deposits as deposit_service  # noqa: E402


async def fund(user_id: int, asset_symbol: str, amount: Decimal) -> None:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise SystemExit(f"no user with id {user_id}")

        network = (
            await db.execute(
                select(AssetNetwork)
                .join(Asset, Asset.id == AssetNetwork.asset_id)
                .where(Asset.symbol == asset_symbol.upper())
                .order_by(AssetNetwork.id)
            )
        ).scalars().first()
        if network is None:
            raise SystemExit(f"no network configured for asset {asset_symbol!r}")

        asset = await db.get(Asset, network.asset_id)
        if amount.as_tuple().exponent < -asset.scale:
            raise SystemExit(
                f"{amount} has more precision than {asset.symbol} allows (scale {asset.scale})"
            )

        if not network.deposit_enabled:
            network.deposit_enabled = True
            await db.flush()

        # Simulate a confirmed on-chain deposit — same as admin credit.
        address = await deposit_service.get_or_create_address(db, user.id, network.id)
        tx_hash = f"0xfund-{user.id}-{asset.symbol}-{int(time.time() * 1000)}"
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

        print(f"credited {amount} {asset.symbol} to user {user.id} ({user.email}) [{deposit.status.value}]")


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: python scripts/fund_user.py <user_id> <asset> <amount>")
    user_id = int(sys.argv[1])
    asset_symbol = sys.argv[2]
    amount = Decimal(sys.argv[3])
    if amount <= 0:
        raise SystemExit("amount must be positive")

    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.set_event_loop(loop)
        loop.run_until_complete(fund(user_id, asset_symbol, amount))
    else:
        asyncio.run(fund(user_id, asset_symbol, amount))


if __name__ == "__main__":
    main()
