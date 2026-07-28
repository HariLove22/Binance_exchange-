"""Seed a handful of P2P ads for local testing.

Creates a few maker users, funds them with crypto, and posts SELL and BUY ads across a couple of
coins and fiats. Idempotent-ish: users are reused by email, and it just adds fresh ads each run.

Run:  ./.venv/Scripts/python.exe seed_p2p.py
"""

import asyncio
import sys
from decimal import Decimal

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select  # noqa: E402

from app.core.db import AsyncSessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Asset, AssetKind, P2PSide, TransactionKind, User  # noqa: E402
from app.services import ledger, p2p  # noqa: E402


async def get_or_create_user(db, email, name):
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email, full_name=name, password_hash=hash_password("Test1234!"), is_verified=True)
        db.add(user)
        await db.flush()
    return user


async def get_or_create_asset(db, symbol):
    asset = (await db.execute(select(Asset).where(Asset.symbol == symbol))).scalar_one_or_none()
    if asset is None:
        asset = Asset(symbol=symbol, name=symbol, kind=AssetKind.CRYPTO, scale=8)
        db.add(asset)
        await db.flush()
    return asset


async def fund(db, user, asset, amount):
    await ledger.credit(
        db, user_id=user.id, asset_id=asset.id, amount=Decimal(amount),
        kind=TransactionKind.ADMIN_CREDIT, idempotency_key=f"seed-fund:{user.id}:{asset.id}:{amount}",
    )


# side, coin, fiat, price, min_fiat, max_fiat, total_qty, methods, terms
ADS = [
    ("SELL", "USDT", "INR", "90.50", "500", "50000", "2000", "UPI,IMPS", "Fast release, online 9am-11pm"),
    ("SELL", "USDT", "INR", "91.20", "1000", "90000", "3000", "UPI,BANK", "Bank transfer only, no third party"),
    ("BUY",  "USDT", "INR", "89.80", "500", "40000", "2000", "UPI", "Pay instantly after you release"),
    ("SELL", "BTC",  "USD", "67200", "50", "5000", "0.5", "BANK,WISE", None),
    ("SELL", "USDT", "USD", "1.001", "20", "3000", "5000", "WISE,PAYPAL", "USD stablecoin, tight spread"),
    ("BUY",  "ETH",  "INR", "312000", "1000", "80000", "3", "UPI,IMPS", None),
]


# Fake completion history per maker email — a few makers look established, one is brand new.
HISTORY = {"amit.p2p@test.com": 34, "neha.p2p@test.com": 12, "raj.p2p@test.com": 0}


async def build_history(db, ad, maker, taker, count):
    """Run `count` full order cycles (open -> paid -> release) so the maker shows real stats."""
    for _ in range(count):
        order = await p2p.open_order(
            db, taker_id=taker.id, ad_id=ad.id,
            fiat_amount=Decimal(ad.min_fiat), payment_method=ad.payment_methods.split(",")[0],
        )
        await p2p.mark_paid(db, user_id=order.buyer_id, order_id=order.id)
        await p2p.release(db, user_id=order.seller_id, order_id=order.id)


async def main():
    async with AsyncSessionLocal() as db:
        # Clean slate so re-running does not stack duplicate ads. Safe for a demo DB — clears only
        # P2P rows, not the ledger (whose entries are append-only and still balance).
        from sqlalchemy import text
        await db.execute(text("DELETE FROM p2p_orders"))
        await db.execute(text("DELETE FROM p2p_ads"))
        await db.flush()

        makers = [
            await get_or_create_user(db, "amit.p2p@test.com", "Amit Sharma"),
            await get_or_create_user(db, "neha.p2p@test.com", "Neha Verma"),
            await get_or_create_user(db, "raj.p2p@test.com", "Raj Patel"),
        ]
        taker = await get_or_create_user(db, "buyer.p2p@test.com", "Test Buyer")

        # Fund every maker generously in every coin so SELL-ad escrow always works.
        posted = 0
        first_sell_ad: dict[int, object] = {}
        for i, (side, coin, fiat, price, mn, mx, qty, methods, terms) in enumerate(ADS):
            asset = await get_or_create_asset(db, coin)
            maker = makers[i % len(makers)]
            await fund(db, maker, asset, "1000000")  # plenty for escrow + history
            ad = await p2p.create_ad(
                db, maker_id=maker.id, side=P2PSide(side), asset_id=asset.id, fiat=fiat,
                price=Decimal(price), min_fiat=Decimal(mn), max_fiat=Decimal(mx),
                total_qty=Decimal(qty), payment_methods=methods, terms=terms,
            )
            posted += 1
            # Remember the first SELL ad per maker to build a completed-order track record on.
            if P2PSide(side) is P2PSide.SELL and maker.id not in first_sell_ad:
                first_sell_ad[maker.id] = ad

        for maker in makers:
            n = HISTORY.get(maker.email, 0)
            ad = first_sell_ad.get(maker.id)
            if n and ad is not None:
                await build_history(db, ad, maker, taker, n)

        await db.commit()

        print(f"Seeded {posted} P2P ads across {len(makers)} makers, with completed-order history.")
        print("Maker logins (password: Test1234!):")
        for m in makers:
            print(f"  {m.email} — {HISTORY.get(m.email, 0)} completed orders")
        print(f"Buyer login: {taker.email}")


if __name__ == "__main__":
    asyncio.run(main())
