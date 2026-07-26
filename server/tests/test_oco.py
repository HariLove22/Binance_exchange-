"""OCO (one-cancels-other): a take-profit limit paired with a stop-loss stop.

The property that makes it an OCO and not two orders: exactly one leg ever executes. When either leg
activates, the other is canceled, and the two legs never both hold funds. These tests pin both
outcomes (limit fills / stop fires) and the money invariant underneath.
"""

from decimal import Decimal

import pytest

from app.models import AccountType, OrderSide, OrderStatus, OrderType
from app.services import ledger, trading
from tests.test_trading import bal, fund, make_market, make_user
from tests.test_stops import rest_liquidity

REF = Decimal("100")  # pretend the market is at 100 for the bracket check


async def sell_oco(db, market, user, qty="1"):
    return await trading.place_oco(
        db, user_id=user.id, market=market, side=OrderSide.SELL, quantity=Decimal(qty),
        limit_price=Decimal("110"), stop_price=Decimal("90"), stop_limit_price=Decimal("89"),
        reference_price=REF,
    )


class TestPlacement:
    async def test_legs_created_only_limit_locks(self, db):
        m = await make_market(db)
        u = await make_user(db, "oco-place@example.com")
        await fund(db, u, m.base_asset_id, "10")

        oco = await sell_oco(db, m, u)
        assert oco.limit_leg.status is OrderStatus.NEW            # rests in the book
        assert oco.stop_leg.status is OrderStatus.TRIGGER_PENDING  # waits outside it
        assert oco.limit_leg.oco_group_id == oco.stop_leg.oco_group_id
        # Only one leg reserves funds: 1 base for the resting limit sell. The stop holds nothing.
        assert oco.limit_leg.locked_remaining == Decimal("1")
        assert oco.stop_leg.locked_remaining == Decimal("0")
        assert await bal(db, u.id, m.base_asset_id, AccountType.LOCKED) == Decimal("1")
        assert await bal(db, u.id, m.base_asset_id) == Decimal("9")

    async def test_bracket_validated(self, db):
        m = await make_market(db)
        u = await make_user(db, "oco-bracket@example.com")
        await fund(db, u, m.base_asset_id, "10")
        with pytest.raises(trading.TradingError, match="limit above and the stop below"):
            await trading.place_oco(
                db, user_id=u.id, market=m, side=OrderSide.SELL, quantity=Decimal("1"),
                limit_price=Decimal("90"), stop_price=Decimal("110"),  # both on the wrong side
                stop_limit_price=Decimal("109"), reference_price=REF,
            )


class TestExclusion:
    async def test_limit_fill_cancels_stop(self, db):
        m = await make_market(db)
        u = await make_user(db, "oco-limitfill@example.com")
        await fund(db, u, m.base_asset_id, "10")
        oco = await sell_oco(db, m, u)

        # A buyer lifts the resting 110 sell → the limit leg fills, so the stop leg is canceled.
        buyer = await make_user(db, "oco-buyer@example.com")
        await fund(db, buyer, m.quote_asset_id, "1000")
        await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("110"))

        assert oco.limit_leg.status is OrderStatus.FILLED
        assert oco.stop_leg.status is OrderStatus.CANCELED
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("110")  # sold 1 @ 110

    async def test_stop_fire_cancels_limit(self, db):
        m = await make_market(db)
        u = await make_user(db, "oco-stopfire@example.com")
        await fund(db, u, m.base_asset_id, "10")
        oco = await sell_oco(db, m, u)

        # Somewhere to sell when the stop fires: a resting bid at 89.
        await rest_liquidity(db, m, side=OrderSide.BUY, qty=5, price=89)

        fired = await trading.check_triggers(db, m, Decimal("89"))
        assert oco.stop_leg.id in fired
        assert oco.stop_leg.status is OrderStatus.FILLED
        assert oco.limit_leg.status is OrderStatus.CANCELED
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("89")  # sold 1 @ 89
        # No base is double-locked: the limit leg released its reservation when it was canceled.
        assert await bal(db, u.id, m.base_asset_id, AccountType.LOCKED) == Decimal("0")

    async def test_cancel_one_leg_cancels_both(self, db):
        m = await make_market(db)
        u = await make_user(db, "oco-cancelboth@example.com")
        await fund(db, u, m.base_asset_id, "10")
        oco = await sell_oco(db, m, u)

        await trading.cancel_order(db, user_id=u.id, order_id=oco.limit_leg.id)
        assert oco.limit_leg.status is OrderStatus.CANCELED
        assert oco.stop_leg.status is OrderStatus.CANCELED
        # Everything is released — the full base balance is available again.
        assert await bal(db, u.id, m.base_asset_id) == Decimal("10")
        assert await bal(db, u.id, m.base_asset_id, AccountType.LOCKED) == Decimal("0")


class TestInvariants:
    async def test_trial_balance_zero_after_stop_leg_fills(self, db):
        m = await make_market(db, maker_fee="0.001", taker_fee="0.001")
        u = await make_user(db, "oco-inv@example.com")
        await fund(db, u, m.base_asset_id, "10")
        await sell_oco(db, m, u)
        await rest_liquidity(db, m, side=OrderSide.BUY, qty=5, price=89)
        await trading.check_triggers(db, m, Decimal("89"))

        totals = await ledger.trial_balance(db)
        assert totals["TBASE"] == Decimal(0)
        assert totals["TQUOTE"] == Decimal(0)
