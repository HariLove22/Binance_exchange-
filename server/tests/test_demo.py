"""Demo (paper) trading — virtual funds, live-priced fills, no real-money impact.

The demo sandbox never touches the ledger, so these assert its own arithmetic: creation seeds virtual
USDT, a buy spends USDT for base and a sell reverses it (minus a simulated fee), and reset restores
the starting funds.
"""

from decimal import Decimal

import pytest

from app.models import OrderSide
from app.services import demo, ledger
from tests.test_trading import make_user

PRICES = {"BTC": Decimal("50000"), "ETH": Decimal("2000")}


async def price_of(symbol: str):
    return PRICES.get(symbol.upper())


def held(account, symbol: str) -> Decimal:
    for h in account.holdings:
        if h.symbol == symbol:
            return h.quantity
    return Decimal(0)


class TestDemo:
    async def test_create_seeds_virtual_usdt(self, db):
        u = await make_user(db, "demo-create@example.com")
        acct = await demo.create_account(db, u.id)
        assert held(acct, "USDT") == Decimal("10000")
        with pytest.raises(demo.DemoError, match="already exists"):
            await demo.create_account(db, u.id)

    async def test_buy_then_sell(self, db):
        u = await make_user(db, "demo-trade@example.com")
        acct = await demo.create_account(db, u.id)

        # Buy 0.1 BTC @ 50000 = 5000 + 5 fee → USDT 10000 - 5005 = 4995.
        await demo.trade(db, account=acct, base_symbol="BTC", side=OrderSide.BUY, quantity=Decimal("0.1"), price_of=price_of)
        assert held(acct, "BTC") == Decimal("0.1")
        assert held(acct, "USDT") == Decimal("4995")

        # Sell it back @ 50000 = 5000 - 5 fee → USDT 4995 + 4995 = 9990 (fee paid twice).
        await demo.trade(db, account=acct, base_symbol="BTC", side=OrderSide.SELL, quantity=Decimal("0.1"), price_of=price_of)
        assert held(acct, "BTC") == Decimal("0")
        assert held(acct, "USDT") == Decimal("9990")

    async def test_cannot_overspend_or_oversell(self, db):
        u = await make_user(db, "demo-limits@example.com")
        acct = await demo.create_account(db, u.id)
        with pytest.raises(demo.DemoError, match="not enough virtual USDT"):
            await demo.trade(db, account=acct, base_symbol="BTC", side=OrderSide.BUY, quantity=Decimal("1"), price_of=price_of)
        with pytest.raises(demo.DemoError, match="not enough BTC"):
            await demo.trade(db, account=acct, base_symbol="BTC", side=OrderSide.SELL, quantity=Decimal("1"), price_of=price_of)

    async def test_reset_restores_funds(self, db):
        u = await make_user(db, "demo-reset@example.com")
        acct = await demo.create_account(db, u.id)
        await demo.trade(db, account=acct, base_symbol="ETH", side=OrderSide.BUY, quantity=Decimal("1"), price_of=price_of)
        assert held(acct, "ETH") == Decimal("1")
        await demo.reset_account(db, acct)
        assert held(acct, "USDT") == Decimal("10000")
        assert held(acct, "ETH") == Decimal("0")

    async def test_demo_does_not_touch_the_ledger(self, db):
        u = await make_user(db, "demo-ledger@example.com")
        acct = await demo.create_account(db, u.id)
        await demo.trade(db, account=acct, base_symbol="BTC", side=OrderSide.BUY, quantity=Decimal("0.05"), price_of=price_of)
        # No real ledger entries for demo — the trial balance is empty/zero, not inflated.
        assert all(v == Decimal(0) for v in (await ledger.trial_balance(db)).values())
