"""VIP fee tiers: tier selection by 30-day volume, and the tier's taker fee applied by the engine."""

from datetime import datetime, timezone
from decimal import Decimal

from app.models import AccountType, OrderSide, OrderType
from app.services import ledger, trading, vip
from tests.test_trading import bal, make_market, make_user, fund

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


class TestTierSelection:
    def test_tier_for_volume(self):
        assert vip.tier_for_volume(Decimal("0")).level == 0
        assert vip.tier_for_volume(Decimal("9999")).level == 0
        assert vip.tier_for_volume(Decimal("10000")).level == 1
        assert vip.tier_for_volume(Decimal("500000")).level == 2
        assert vip.tier_for_volume(Decimal("50000000")).level == 4

    async def test_new_user_is_regular(self, db):
        u = await make_user(db, "vip-new@example.com")
        tier, vol = await vip.user_tier(db, u.id, NOW)
        assert tier.level == 0 and vol == Decimal("0")


class TestFeeApplied:
    async def test_taker_fee_override_lowers_fee(self, db):
        # 1% market fee so the arithmetic is obvious; override the taker to 0.5%.
        m = await make_market(db, maker_fee="0.01", taker_fee="0.01")
        seller = await make_user(db, "vip-s@example.com")
        buyer = await make_user(db, "vip-b@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        # Buyer is the taker with a 0.5% override → pays 0.005 base fee, not 0.01.
        await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                  order_type=OrderType.MARKET, quantity=Decimal("1"), taker_fee=Decimal("0.005"))

        assert await bal(db, buyer.id, m.base_asset_id) == Decimal("0.995")   # 1 - 0.5% override
        # Seller is the maker → still pays the 1% market maker fee.
        assert await bal(db, seller.id, m.quote_asset_id) == Decimal("99")
        assert (await ledger.trial_balance(db))["TBASE"] == Decimal(0)
        assert (await ledger.trial_balance(db))["TQUOTE"] == Decimal(0)

    async def test_default_uses_market_fee(self, db):
        m = await make_market(db, maker_fee="0.01", taker_fee="0.01")
        seller = await make_user(db, "vip-s2@example.com")
        buyer = await make_user(db, "vip-b2@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")
        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        # No override → the market's 1% taker fee.
        await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                  order_type=OrderType.MARKET, quantity=Decimal("1"))
        assert await bal(db, buyer.id, m.base_asset_id) == Decimal("0.99")

    async def test_volume_counts_user_trades(self, db):
        m = await make_market(db)
        seller = await make_user(db, "vip-vol-s@example.com")
        buyer = await make_user(db, "vip-vol-b@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "10000")
        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("2"), price=Decimal("100"))
        await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                  order_type=OrderType.MARKET, quantity=Decimal("2"))
        # 2 @ 100 = 200 quote volume for the buyer.
        _, vol = await vip.user_tier(db, buyer.id, NOW)
        assert vol == Decimal("200")
