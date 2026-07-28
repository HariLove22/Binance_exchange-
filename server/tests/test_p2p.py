"""P2P escrow lifecycle: the crypto is locked on open, and leaves only by release or refund.

The invariant under every path: the seller's crypto is escrowed while an order is live, exactly one
of {released to buyer, refunded to seller} ever happens, and the trial balance stays at zero — no
crypto is created or destroyed. The fiat is off-platform and never appears on our books.
"""

from decimal import Decimal

import pytest

from app.models import Asset, AssetKind, P2PAdStatus, P2POrderStatus, P2PSide, User, UserRole
from app.services import ledger, p2p
from tests.test_trading import bal, fund, make_user


async def make_asset(db, symbol="USDT") -> Asset:
    a = Asset(symbol=symbol, name=symbol, kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def make_admin(db, email) -> User:
    u = User(email=email, full_name="Admin", password_hash="x", is_verified=True, role=UserRole.ADMIN)
    db.add(u)
    await db.flush()
    return u


async def sell_ad(db, maker, asset, *, qty="100"):
    return await p2p.create_ad(
        db, maker_id=maker.id, side=P2PSide.SELL, asset_id=asset.id, fiat="INR",
        price=Decimal("90"), min_fiat=Decimal("100"), max_fiat=Decimal("9000"),
        total_qty=Decimal(qty), payment_methods="UPI,IMPS",
    )


class TestSellAd:
    async def test_full_release_moves_crypto(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-seller@example.com")   # sells crypto
        taker = await make_user(db, "p2p-buyer@example.com")    # pays fiat
        await fund(db, maker, asset.id, "100")

        ad = await sell_ad(db, maker, asset)
        order = await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                     fiat_amount=Decimal("900"), payment_method="UPI")

        # 900 INR / 90 = 10 USDT escrowed from the seller.
        assert order.crypto_amount == Decimal("10")
        assert order.seller_id == maker.id and order.buyer_id == taker.id
        assert await bal(db, maker.id, asset.id) == Decimal("90")            # available
        assert await bal(db, maker.id, asset.id, ledger.AccountType.LOCKED) == Decimal("10")
        assert ad.available_qty == Decimal("90")

        # Buyer pays off-platform → marks paid → seller releases.
        await p2p.mark_paid(db, user_id=taker.id, order_id=order.id)
        await p2p.release(db, user_id=maker.id, order_id=order.id)

        assert order.status is P2POrderStatus.RELEASED
        assert await bal(db, taker.id, asset.id) == Decimal("10")            # buyer got crypto
        assert await bal(db, maker.id, asset.id, ledger.AccountType.LOCKED) == Decimal("0")
        assert (await ledger.trial_balance(db))[asset.symbol] == Decimal("0")

    async def test_open_order_needs_escrow_funds(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-poor@example.com")
        taker = await make_user(db, "p2p-t2@example.com")
        # Seller funded only 5 USDT but the ad claims 100.
        await fund(db, maker, asset.id, "5")
        ad = await sell_ad(db, maker, asset)
        with pytest.raises(p2p.P2PError, match="insufficient"):
            await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                 fiat_amount=Decimal("900"), payment_method="UPI")


class TestBuyAd:
    async def test_taker_is_seller_on_buy_ad(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-buymaker@example.com")  # wants to buy → pays fiat
        taker = await make_user(db, "p2p-sellertaker@example.com")  # sells crypto → escrowed
        await fund(db, taker, asset.id, "50")

        ad = await p2p.create_ad(
            db, maker_id=maker.id, side=P2PSide.BUY, asset_id=asset.id, fiat="INR",
            price=Decimal("90"), min_fiat=Decimal("100"), max_fiat=Decimal("9000"),
            total_qty=Decimal("100"), payment_methods="UPI",
        )
        order = await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                     fiat_amount=Decimal("900"), payment_method="UPI")
        # On a BUY ad the taker sells: escrow comes from the taker.
        assert order.seller_id == taker.id and order.buyer_id == maker.id
        assert await bal(db, taker.id, asset.id, ledger.AccountType.LOCKED) == Decimal("10")

        await p2p.mark_paid(db, user_id=maker.id, order_id=order.id)  # buyer is the maker here
        await p2p.release(db, user_id=taker.id, order_id=order.id)    # seller is the taker
        assert await bal(db, maker.id, asset.id) == Decimal("10")


class TestCancelAndAuth:
    async def test_cancel_refunds_seller_and_restores_ad(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-c-seller@example.com")
        taker = await make_user(db, "p2p-c-buyer@example.com")
        await fund(db, maker, asset.id, "100")
        ad = await sell_ad(db, maker, asset)
        order = await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                     fiat_amount=Decimal("900"), payment_method="UPI")
        assert ad.available_qty == Decimal("90")

        await p2p.cancel(db, user_id=taker.id, order_id=order.id)
        assert order.status is P2POrderStatus.CANCELED
        assert await bal(db, maker.id, asset.id) == Decimal("100")           # fully refunded
        assert await bal(db, maker.id, asset.id, ledger.AccountType.LOCKED) == Decimal("0")
        assert ad.available_qty == Decimal("100")                            # restored
        assert (await ledger.trial_balance(db))[asset.symbol] == Decimal("0")

    async def test_only_buyer_marks_paid_only_seller_releases(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-auth-seller@example.com")
        taker = await make_user(db, "p2p-auth-buyer@example.com")
        await fund(db, maker, asset.id, "100")
        ad = await sell_ad(db, maker, asset)
        order = await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                     fiat_amount=Decimal("900"), payment_method="UPI")

        with pytest.raises(p2p.P2PError, match="only the buyer"):
            await p2p.mark_paid(db, user_id=maker.id, order_id=order.id)   # seller can't mark paid
        await p2p.mark_paid(db, user_id=taker.id, order_id=order.id)
        with pytest.raises(p2p.P2PError, match="only the seller"):
            await p2p.release(db, user_id=taker.id, order_id=order.id)     # buyer can't release

    async def test_cannot_release_before_paid(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-early-seller@example.com")
        taker = await make_user(db, "p2p-early-buyer@example.com")
        await fund(db, maker, asset.id, "100")
        ad = await sell_ad(db, maker, asset)
        order = await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                     fiat_amount=Decimal("900"), payment_method="UPI")
        with pytest.raises(p2p.P2PError, match="must mark paid first"):
            await p2p.release(db, user_id=maker.id, order_id=order.id)


class TestDispute:
    async def test_admin_resolves_for_buyer(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-d-seller@example.com")
        taker = await make_user(db, "p2p-d-buyer@example.com")
        admin = await make_admin(db, "p2p-admin@example.com")
        await fund(db, maker, asset.id, "100")
        ad = await sell_ad(db, maker, asset)
        order = await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                     fiat_amount=Decimal("900"), payment_method="UPI")
        await p2p.mark_paid(db, user_id=taker.id, order_id=order.id)
        await p2p.open_dispute(db, user_id=taker.id, order_id=order.id)
        assert order.status is P2POrderStatus.DISPUTED

        await p2p.resolve_dispute(db, admin=admin, order_id=order.id, in_favor_of_buyer=True)
        assert order.status is P2POrderStatus.RELEASED
        assert await bal(db, taker.id, asset.id) == Decimal("10")
        assert (await ledger.trial_balance(db))[asset.symbol] == Decimal("0")

    async def test_non_admin_cannot_resolve(self, db):
        asset = await make_asset(db)
        maker = await make_user(db, "p2p-d2-seller@example.com")
        taker = await make_user(db, "p2p-d2-buyer@example.com")
        await fund(db, maker, asset.id, "100")
        ad = await sell_ad(db, maker, asset)
        order = await p2p.open_order(db, taker_id=taker.id, ad_id=ad.id,
                                     fiat_amount=Decimal("900"), payment_method="UPI")
        await p2p.mark_paid(db, user_id=taker.id, order_id=order.id)
        await p2p.open_dispute(db, user_id=taker.id, order_id=order.id)
        with pytest.raises(p2p.P2PError, match="admin"):
            await p2p.resolve_dispute(db, admin=maker, order_id=order.id, in_favor_of_buyer=False)
