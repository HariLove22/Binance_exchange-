"""Stop (conditional) orders: trigger direction, firing, and the money invariant.

A stop rests OUTSIDE the book with no locked funds until the reference price crosses its trigger,
then it fires through the normal lock+match path. These tests pin the two things that make it a
stop and not a plain order: it holds nothing until fired, and it fires in the right direction.
"""

from decimal import Decimal

import pytest

from app.models import AccountType, OrderSide, OrderStatus, OrderType
from app.services import ledger, trading
from tests.test_trading import bal, fund, make_market, make_user


async def rest_liquidity(db, market, *, side, qty, price):
    """Park a resting limit order so a fired stop has something to match against."""
    maker = await make_user(db, f"mm-{side.value}-{price}@example.com")
    if side is OrderSide.SELL:
        await fund(db, maker, market.base_asset_id, str(qty))
    else:
        await fund(db, maker, market.quote_asset_id, str(qty * price))
    await trading.place_order(db, user_id=maker.id, market=market, side=side,
                              order_type=OrderType.LIMIT, quantity=Decimal(qty), price=Decimal(price))
    return maker


class TestPlacement:
    async def test_stop_holds_no_funds_until_fired(self, db):
        m = await make_market(db)
        u = await make_user(db, "stop-hold@example.com")
        await fund(db, u, m.quote_asset_id, "1000")

        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT,
            quantity=Decimal("1"), trigger_price=Decimal("110"), reference_price=Decimal("100"),
            price=Decimal("111"),
        )
        assert order.status is OrderStatus.TRIGGER_PENDING
        assert order.trigger_above is True  # trigger 110 sits above the 100 reference → fires on a rise
        assert order.locked_remaining == Decimal("0")
        # Nothing locked — the full balance is still available.
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("1000")
        assert await bal(db, u.id, m.quote_asset_id, AccountType.LOCKED) == Decimal("0")

    async def test_direction_inferred_below_market_is_downside_stop(self, db):
        m = await make_market(db)
        u = await make_user(db, "stop-dir@example.com")
        await fund(db, u, m.base_asset_id, "10")

        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.SELL, order_type=OrderType.STOP_MARKET,
            quantity=Decimal("1"), trigger_price=Decimal("90"), reference_price=Decimal("100"),
        )
        assert order.trigger_above is False  # 90 below 100 → a sell-stop that fires on a fall

    async def test_stop_limit_requires_price(self, db):
        m = await make_market(db)
        u = await make_user(db, "stop-noprice@example.com")
        with pytest.raises(trading.TradingError, match="limit price"):
            await trading.place_stop_order(
                db, user_id=u.id, market=m, side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT,
                quantity=Decimal("1"), trigger_price=Decimal("110"), reference_price=Decimal("100"),
            )


class TestFiring:
    async def test_fires_only_when_price_crosses(self, db):
        m = await make_market(db)
        await rest_liquidity(db, m, side=OrderSide.SELL, qty=5, price=112)
        u = await make_user(db, "stop-fire@example.com")
        await fund(db, u, m.quote_asset_id, "1000")

        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT,
            quantity=Decimal("1"), trigger_price=Decimal("110"), reference_price=Decimal("100"),
            price=Decimal("115"),
        )

        # Price still below the trigger → nothing fires.
        fired = await trading.check_triggers(db, m, Decimal("105"))
        assert fired == []
        assert order.status is OrderStatus.TRIGGER_PENDING

        # Price crosses 110 → the stop fires and takes the 112 ask (maker's price).
        fired = await trading.check_triggers(db, m, Decimal("110"))
        assert fired == [order.id]
        assert order.status is OrderStatus.FILLED
        assert await bal(db, u.id, m.base_asset_id) == Decimal("1")
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("888")  # 1000 - 112

    async def test_downside_sell_stop_fires_on_fall(self, db):
        m = await make_market(db)
        await rest_liquidity(db, m, side=OrderSide.BUY, qty=5, price=88)
        u = await make_user(db, "stop-sell@example.com")
        await fund(db, u, m.base_asset_id, "10")

        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.SELL, order_type=OrderType.STOP_MARKET,
            quantity=Decimal("1"), trigger_price=Decimal("90"), reference_price=Decimal("100"),
        )
        # A rise does not fire a downside stop.
        assert await trading.check_triggers(db, m, Decimal("105")) == []
        # A fall through 90 does.
        assert await trading.check_triggers(db, m, Decimal("89")) == [order.id]
        assert order.status is OrderStatus.FILLED
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("88")  # sold 1 @ 88 (the resting bid)

    async def test_fired_stop_rejected_if_funds_gone(self, db):
        m = await make_market(db)
        await rest_liquidity(db, m, side=OrderSide.SELL, qty=5, price=112)
        u = await make_user(db, "stop-broke@example.com")
        await fund(db, u, m.quote_asset_id, "50")  # not enough to buy 1 @ 112

        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT,
            quantity=Decimal("1"), trigger_price=Decimal("110"), reference_price=Decimal("100"),
            price=Decimal("115"),
        )
        fired = await trading.check_triggers(db, m, Decimal("110"))
        assert fired == [order.id]
        assert order.status is OrderStatus.REJECTED  # could not fund → rejected, not left hanging
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("50")  # untouched

    async def test_cancel_pending_stop(self, db):
        m = await make_market(db)
        u = await make_user(db, "stop-cancel@example.com")
        await fund(db, u, m.quote_asset_id, "1000")
        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT,
            quantity=Decimal("1"), trigger_price=Decimal("110"), reference_price=Decimal("100"),
            price=Decimal("111"),
        )
        canceled = await trading.cancel_order(db, user_id=u.id, order_id=order.id)
        assert canceled.status is OrderStatus.CANCELED


class TestInvariants:
    async def test_trial_balance_zero_after_stop_fires(self, db):
        m = await make_market(db, maker_fee="0.001", taker_fee="0.001")
        await rest_liquidity(db, m, side=OrderSide.SELL, qty=5, price=112)
        u = await make_user(db, "stop-inv@example.com")
        await fund(db, u, m.quote_asset_id, "1000")
        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT,
            quantity=Decimal("1"), trigger_price=Decimal("110"), reference_price=Decimal("100"),
            price=Decimal("115"),
        )
        await trading.check_triggers(db, m, Decimal("110"))
        assert order.status is OrderStatus.FILLED

        totals = await ledger.trial_balance(db)
        assert totals["TBASE"] == Decimal(0)
        assert totals["TQUOTE"] == Decimal(0)

    async def test_sweep_fires_across_markets(self, db):
        """sweep_triggers prices each market with a pending stop via the supplied price function."""
        m = await make_market(db)
        await rest_liquidity(db, m, side=OrderSide.SELL, qty=5, price=112)
        u = await make_user(db, "stop-sweep@example.com")
        await fund(db, u, m.quote_asset_id, "1000")
        order = await trading.place_stop_order(
            db, user_id=u.id, market=m, side=OrderSide.BUY, order_type=OrderType.STOP_LIMIT,
            quantity=Decimal("1"), trigger_price=Decimal("110"), reference_price=Decimal("100"),
            price=Decimal("115"),
        )

        async def price_of(symbol: str) -> Decimal:
            return Decimal("110")

        fired = await trading.sweep_triggers(db, price_of)
        assert fired == {m.symbol: [order.id]}
        assert order.status is OrderStatus.FILLED
