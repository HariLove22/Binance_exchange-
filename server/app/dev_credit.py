"""Credit test funds to a user — development only.

    python -m app.dev_credit <email> <asset> <amount>
    python -m app.dev_credit wallet-demo@example.com USDT 5000

There is no deposit pipeline yet (it needs a custody provider), so this is how a balance becomes
non-zero for now. It posts a real double-entry `ADMIN_CREDIT` transaction through the ledger — it
does not set a number — so the trial balance stays zero and the entry is visible in the ledger
like any other.

Refuses to run outside a development environment. In production this would mint balances no
deposit backs, breaking the reconciliation that matters: user balances against on-chain holdings.
"""

import asyncio
import sys
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models import Asset, TransactionKind, User
from app.services import ledger


async def main(email: str, symbol: str, amount_str: str) -> int:
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

        asset = (await db.execute(select(Asset).where(Asset.symbol == symbol.upper()))).scalar_one_or_none()
        if asset is None:
            print(f"no asset {symbol!r}")
            return 1

        if amount.as_tuple().exponent < -asset.scale:
            print(f"{amount_str} has more precision than {asset.symbol} allows (scale {asset.scale})")
            return 2

        # Distinct per invocation so repeated top-ups both apply — idempotency is for machine
        # retries, not human intent.
        import time

        key = f"dev-credit:{user.id}:{asset.symbol}:{amount_str}:{int(time.time() * 1000)}"
        txn = await ledger.credit(
            db,
            user_id=user.id,
            asset_id=asset.id,
            amount=amount,
            kind=TransactionKind.ADMIN_CREDIT,
            idempotency_key=key,
            reference="dev_credit script",
        )
        await db.commit()

        print(f"credited {amount} {asset.symbol} to {email} (txn {txn.id if txn else 'already applied'})")
        return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3])))
