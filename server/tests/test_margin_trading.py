"""Margin trading through the matching engine: leveraged buys and short sells.

A margin order locks and settles in the MARGIN wallet, so it can fill against an ordinary spot maker
while the two sides settle in different wallets. Auto-borrow covers any shortfall — borrowing quote
for a buy, base for a sell (a short). The trial balance stays zero: borrowed funds come from the pool
and the counterparty's funds move as always.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.models import AccountType, MarginLoanStatus, MarginMode, MarginTier, OrderSide, OrderStatus, OrderType, WALLET_SPOT
from app.services import ledger, margin
from tests.test_trading import make_market, make_user, fund, bal

PRICES = {"TBASE": Decimal("100"), "TQUOTE": Decimal("1")}
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def price_of(symbol: str):
    return PRICES.get(symbol)


async def mbal(db, user_id, asset_id, wallet, account_type=AccountType.AVAILABLE):
    return (await ledger.get_or_create_account(db, asset_id, account_type, user_id, wallet=wallet)).balance


class TestMarginBuy:
    async def test_leveraged_buy_auto_borrows_and_settles_in_margin(self, db):
        m = await make_market(db)
        seller = await make_user(db, "mt-seller@example.com")   # plain spot maker
        buyer = await make_user(db, "mt-buyer@example.com")
        await fund(db, seller, m.base_asset_id, "10")
        await fund(db, buyer, m.quote_asset_id, "1000")

        # Spot seller rests 5 TBASE @ 100.
        await trading_place_sell(db, seller, m, qty="5", price="100")

        # Buyer: cross margin, 5x, deposits only 200 quote as collateral.
        acct = await margin.open_account(db, user_id=buyer.id, tier=MarginTier.PRO, leverage=Decimal("5"))
        await margin.transfer_collateral(db, account=acct, asset_id=m.quote_asset_id, amount=Decimal("200"), deposit=True)

        # Buy 5 @ 100 needs 500 quote; only 200 is there → auto-borrow 300.
        placed = await margin.place_margin_order(
            db, account=acct, market=m, side=OrderSide.BUY, order_type=OrderType.LIMIT,
            quantity=Decimal("5"), price=Decimal("100"), price_of=price_of, now=T0,
        )
        assert placed.order.status is OrderStatus.FILLED
        assert placed.order.wallet == "MARGIN"

        # A 300-quote loan was opened.
        loans = await margin.open_loans(db, acct)
        assert len(loans) == 1 and loans[0].principal == Decimal("300")

        # Buyer got 5 base in the MARGIN wallet; spot is untouched.
        assert await mbal(db, buyer.id, m.base_asset_id, "MARGIN") == Decimal("5")
        assert await bal(db, buyer.id, m.base_asset_id) == Decimal("0")           # spot base
        # Spot quote = 1000 - 200 collateral; the trade itself borrowed + settled in margin only.
        assert await bal(db, buyer.id, m.quote_asset_id) == Decimal("800")
        # Seller received 500 quote in spot.
        assert await bal(db, seller.id, m.quote_asset_id) == Decimal("500")
        assert (await ledger.trial_balance(db))["TQUOTE"] == Decimal(0)
        assert (await ledger.trial_balance(db))["TBASE"] == Decimal(0)


class TestShortSell:
    async def test_margin_sell_borrows_base_and_shorts(self, db):
        m = await make_market(db)
        bidder = await make_user(db, "mt-bidder@example.com")   # spot buyer resting a bid
        shorter = await make_user(db, "mt-shorter@example.com")
        await fund(db, bidder, m.quote_asset_id, "1000")
        await fund(db, shorter, m.quote_asset_id, "1000")  # collateral

        # Spot bidder rests a BUY 3 @ 100.
        await trading_place_buy(db, bidder, m, qty="3", price="100")

        # Shorter: cross margin, 5x, deposits 1000 quote collateral, holds NO base.
        acct = await margin.open_account(db, user_id=shorter.id, tier=MarginTier.PRO, leverage=Decimal("5"))
        await margin.transfer_collateral(db, account=acct, asset_id=m.quote_asset_id, amount=Decimal("1000"), deposit=True)

        placed = await margin.place_margin_order(
            db, account=acct, market=m, side=OrderSide.SELL, order_type=OrderType.LIMIT,
            quantity=Decimal("3"), price=Decimal("100"), price_of=price_of, now=T0,
        )
        assert placed.order.status is OrderStatus.FILLED

        # Borrowed 3 base (the short), sold it for 300 quote into the margin wallet.
        loans = await margin.open_loans(db, acct)
        assert len(loans) == 1 and loans[0].asset_id == m.base_asset_id and loans[0].principal == Decimal("3")
        assert await mbal(db, shorter.id, m.base_asset_id, "MARGIN") == Decimal("0")   # sold what it borrowed
        assert await mbal(db, shorter.id, m.quote_asset_id, "MARGIN") == Decimal("1300")  # 1000 + 300
        assert (await ledger.trial_balance(db))["TBASE"] == Decimal(0)
        assert (await ledger.trial_balance(db))["TQUOTE"] == Decimal(0)


class TestState:
    async def test_account_state_reflects_leverage(self, db):
        m = await make_market(db)
        u = await make_user(db, "mt-state@example.com")
        await fund(db, u, m.quote_asset_id, "1000")
        acct = await margin.open_account(db, user_id=u.id, tier=MarginTier.PRO, leverage=Decimal("5"))
        await margin.transfer_collateral(db, account=acct, asset_id=m.quote_asset_id, amount=Decimal("1000"), deposit=True)

        st = await margin.account_state(db, acct, price_of)
        assert st.equity_usd == Decimal("1000")
        assert st.debt_usd == Decimal("0")
        assert st.max_borrow_usd == Decimal("4000")   # 1000 * 5 - 1000
        assert st.margin_level is None                # no debt yet


# --- helpers: place plain spot maker orders --------------------------------------------------------

from app.services import trading  # noqa: E402


async def trading_place_sell(db, user, market, *, qty, price):
    return await trading.place_order(db, user_id=user.id, market=market, side=OrderSide.SELL,
                                     order_type=OrderType.LIMIT, quantity=Decimal(qty), price=Decimal(price))


async def trading_place_buy(db, user, market, *, qty, price):
    return await trading.place_order(db, user_id=user.id, market=market, side=OrderSide.BUY,
                                     order_type=OrderType.LIMIT, quantity=Decimal(qty), price=Decimal(price))
