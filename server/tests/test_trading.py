"""The matching engine and trade settlement.

Each test is a property that must hold for money to move correctly: price-time priority, trade at
the maker's price, locks that release exactly, fees on the received side, and — underneath all of
it — the trial balance staying at zero. Money correctness is checked by asserting balances AND that
nothing was created or destroyed.
"""

from decimal import Decimal

import pytest

from app.models import (
    AccountType,
    Asset,
    AssetKind,
    Market,
    OrderSide,
    OrderStatus,
    OrderType,
    User,
)
from app.services import ledger
from app.services import trading
from app.services.trading import TradingError


async def make_user(db, email: str) -> User:
    u = User(email=email, full_name="T", password_hash="x", is_verified=True)
    db.add(u)
    await db.flush()
    return u


async def make_market(db, maker_fee="0", taker_fee="0") -> Market:
    base = Asset(symbol="TBASE", name="Base", kind=AssetKind.CRYPTO, scale=8)
    quote = Asset(symbol="TQUOTE", name="Quote", kind=AssetKind.CRYPTO, scale=8)
    db.add_all([base, quote])
    await db.flush()
    m = Market(
        symbol="TBASETQUOTE", base_asset_id=base.id, quote_asset_id=quote.id,
        price_tick=Decimal("0.01"), qty_step=Decimal("0.0001"), min_notional=Decimal("1"),
        maker_fee=Decimal(maker_fee), taker_fee=Decimal(taker_fee), enabled=True,
    )
    db.add(m)
    await db.flush()
    return m


async def fund(db, user, asset_id, amount):
    await ledger.credit(
        db, user_id=user.id, asset_id=asset_id, amount=Decimal(amount),
        kind=ledger.TransactionKind.DEPOSIT, idempotency_key=f"fund:{user.id}:{asset_id}:{amount}",
    )


async def bal(db, user_id, asset_id, account_type=AccountType.AVAILABLE):
    acct = await ledger.get_or_create_account(db, asset_id, account_type, user_id)
    return acct.balance


class TestMatching:
    async def test_limit_buy_fills_against_resting_sell(self, db):
        m = await make_market(db)
        seller = await make_user(db, "seller@example.com")
        buyer = await make_user(db, "buyer@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        # Seller rests an ask: 2 @ 100.
        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("2"), price=Decimal("100"))
        # Buyer takes it: buy 2 @ 100.
        placed = await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                           order_type=OrderType.LIMIT, quantity=Decimal("2"), price=Decimal("100"))

        assert placed.order.status is OrderStatus.FILLED
        assert len(placed.trades) == 1
        assert placed.trades[0].price == Decimal("100")
        # Buyer got 2 base, spent 200 quote.
        assert await bal(db, buyer.id, m.base_asset_id) == Decimal("2")
        assert await bal(db, buyer.id, m.quote_asset_id) == Decimal("800")
        # Seller got 200 quote, gave 2 base.
        assert await bal(db, seller.id, m.quote_asset_id) == Decimal("200")
        assert await bal(db, seller.id, m.base_asset_id) == Decimal("8")

    async def test_trade_executes_at_maker_price_not_taker(self, db):
        """Maker rests at 100; taker is willing to pay up to 105. Trade is at 100 — the taker gets
        the improvement."""
        m = await make_market(db)
        seller = await make_user(db, "s2@example.com")
        buyer = await make_user(db, "b2@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        placed = await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                           order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("105"))

        assert placed.trades[0].price == Decimal("100")
        # Buyer only locked and spent 100, not 105 — no over-lock, no refund needed.
        assert await bal(db, buyer.id, m.quote_asset_id) == Decimal("900")

    async def test_price_time_priority(self, db):
        """Two asks at the same price; the earlier one fills first."""
        m = await make_market(db)
        s1 = await make_user(db, "early@example.com")
        s2 = await make_user(db, "late@example.com")
        buyer = await make_user(db, "b3@example.com")
        await fund(db, s1, m.base_asset_id, "10")
        await fund(db, s2, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        first = await trading.place_order(db, user_id=s1.id, market=m, side=OrderSide.SELL,
                                          order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        await trading.place_order(db, user_id=s2.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        placed = await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                           order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))

        # Only the earlier seller's order was hit.
        assert placed.trades[0].maker_order_id == first.order.id
        assert await bal(db, s1.id, m.quote_asset_id) == Decimal("100")
        assert await bal(db, s2.id, m.quote_asset_id) == Decimal("0")

    async def test_partial_fill_rests_remainder(self, db):
        m = await make_market(db)
        seller = await make_user(db, "s4@example.com")
        buyer = await make_user(db, "b4@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        # Buyer wants 3 but only 1 is available at their price.
        placed = await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                           order_type=OrderType.LIMIT, quantity=Decimal("3"), price=Decimal("100"))

        assert placed.order.status is OrderStatus.PARTIALLY_FILLED
        assert placed.order.filled_quantity == Decimal("1")
        # Remaining 2 @ 100 = 200 stays locked for the resting order.
        assert placed.order.locked_remaining == Decimal("200")
        assert await bal(db, buyer.id, m.quote_asset_id, AccountType.LOCKED) == Decimal("200")

    async def test_market_buy_sweeps_multiple_levels(self, db):
        m = await make_market(db)
        seller = await make_user(db, "s5@example.com")
        buyer = await make_user(db, "b5@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("110"))
        placed = await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                           order_type=OrderType.MARKET, quantity=Decimal("2"))

        assert placed.order.status is OrderStatus.FILLED
        assert len(placed.trades) == 2
        # Spent 100 + 110 = 210.
        assert await bal(db, buyer.id, m.quote_asset_id) == Decimal("790")
        assert await bal(db, buyer.id, m.base_asset_id) == Decimal("2")

    async def test_market_order_rejected_on_empty_book(self, db):
        m = await make_market(db)
        buyer = await make_user(db, "b6@example.com")
        await fund(db, buyer, m.quote_asset_id, "1000")
        with pytest.raises(TradingError, match="no liquidity"):
            await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                      order_type=OrderType.MARKET, quantity=Decimal("1"))


class TestFunds:
    async def test_insufficient_funds_rejected(self, db):
        m = await make_market(db)
        seller = await make_user(db, "s7@example.com")
        buyer = await make_user(db, "b7@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "50")  # not enough for 1 @ 100

        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        with pytest.raises(TradingError, match="insufficient"):
            await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                      order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))

    async def test_cancel_releases_locked_funds(self, db):
        m = await make_market(db)
        buyer = await make_user(db, "b8@example.com")
        await fund(db, buyer, m.quote_asset_id, "1000")

        placed = await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                           order_type=OrderType.LIMIT, quantity=Decimal("2"), price=Decimal("100"))
        assert await bal(db, buyer.id, m.quote_asset_id) == Decimal("800")  # 200 locked
        assert await bal(db, buyer.id, m.quote_asset_id, AccountType.LOCKED) == Decimal("200")

        await trading.cancel_order(db, user_id=buyer.id, order_id=placed.order.id)
        assert await bal(db, buyer.id, m.quote_asset_id) == Decimal("1000")  # fully released
        assert await bal(db, buyer.id, m.quote_asset_id, AccountType.LOCKED) == Decimal("0")


class TestFees:
    async def test_taker_and_maker_fees_go_to_income(self, db):
        # 1% both sides to make the arithmetic obvious.
        m = await make_market(db, maker_fee="0.01", taker_fee="0.01")
        seller = await make_user(db, "s9@example.com")  # maker
        buyer = await make_user(db, "b9@example.com")   # taker
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))
        await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                  order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100"))

        # Buyer receives base, pays 1% base fee → gets 0.99 base.
        assert await bal(db, buyer.id, m.base_asset_id) == Decimal("0.99")
        # Seller receives quote, pays 1% quote fee → gets 99 quote.
        assert await bal(db, seller.id, m.quote_asset_id) == Decimal("99")
        # Fees collected: 0.01 base + 1 quote.
        assert await bal(db, None, m.base_asset_id, AccountType.FEE_INCOME) == Decimal("0.01")
        assert await bal(db, None, m.quote_asset_id, AccountType.FEE_INCOME) == Decimal("1")


class TestInvariants:
    async def test_trial_balance_zero_after_trading(self, db):
        """Underneath every property above: no money was created or destroyed."""
        m = await make_market(db, maker_fee="0.001", taker_fee="0.001")
        seller = await make_user(db, "inv-s@example.com")
        buyer = await make_user(db, "inv-b@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        await trading.place_order(db, user_id=seller.id, market=m, side=OrderSide.SELL,
                                  order_type=OrderType.LIMIT, quantity=Decimal("2"), price=Decimal("100"))
        await trading.place_order(db, user_id=buyer.id, market=m, side=OrderSide.BUY,
                                  order_type=OrderType.MARKET, quantity=Decimal("1.5"))

        totals = await ledger.trial_balance(db)
        assert totals["TBASE"] == Decimal(0)
        assert totals["TQUOTE"] == Decimal(0)

    async def test_filters_reject_bad_orders(self, db):
        m = await make_market(db)
        u = await make_user(db, "filter@example.com")
        await fund(db, u, m.quote_asset_id, "1000")

        with pytest.raises(TradingError, match="multiple of"):  # price not a tick multiple
            await trading.place_order(db, user_id=u.id, market=m, side=OrderSide.BUY,
                                      order_type=OrderType.LIMIT, quantity=Decimal("1"), price=Decimal("100.001"))
        with pytest.raises(TradingError, match="below minimum"):  # notional too small
            await trading.place_order(db, user_id=u.id, market=m, side=OrderSide.BUY,
                                      order_type=OrderType.LIMIT, quantity=Decimal("0.001"), price=Decimal("100"))
