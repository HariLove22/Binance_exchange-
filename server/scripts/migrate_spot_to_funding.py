"""One-off: move every user's spendable SPOT balance into the new FUNDING (main) wallet.

Deposits now land in FUNDING and you transfer into SPOT/MARGIN/FUTURES to trade. This shifts the
existing spot balances to match. Only AVAILABLE is moved — LOCKED stays in SPOT so open spot orders
keep their escrow. Internal/service accounts (the market maker) are skipped so the order book keeps
its liquidity. Uses ledger.transfer_wallet, so every move is a balanced double-entry.

Usage (from server/, venv active):
    python scripts/migrate_spot_to_funding.py
"""

import asyncio
import selectors
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select  # noqa: E402

from app.core.db import AsyncSessionLocal  # noqa: E402
from app.models import User, WALLET_FUNDING, WALLET_SPOT  # noqa: E402
from app.services import ledger  # noqa: E402

# Service accounts whose spot funds back the order book / house — leave them in SPOT.
SKIP_EMAIL_SUFFIXES = ("novex.internal",)


async def run() -> None:
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User))).scalars().all()
        moved = 0
        for u in users:
            if any(u.email.endswith(s) for s in SKIP_EMAIL_SUFFIXES):
                print(f"skip (service): {u.email}")
                continue
            for b in await ledger.balances(db, u.id, wallet=WALLET_SPOT):
                if b.available <= 0:
                    continue
                await ledger.transfer_wallet(
                    db, user_id=u.id, asset_id=b.asset_id, amount=b.available,
                    from_wallet=WALLET_SPOT, to_wallet=WALLET_FUNDING,
                    idempotency_key=f"migrate-funding:{u.id}:{b.symbol}:{b.available}",
                    reference="migrate spot->funding",
                )
                print(f"  {u.email}: {b.available} {b.symbol}  SPOT -> FUNDING")
                moved += 1
        await db.commit()
        print(f"done — {moved} balances moved. Trial balance:", await ledger.trial_balance(db))


def main() -> None:
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run())
    else:
        asyncio.run(run())


if __name__ == "__main__":
    main()
