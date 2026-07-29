"""Margin liquidation: an underwater leveraged position is force-closed and its loans repaid.

Health is the margin level (gross assets / debt). Above the margin-call band it is safe; at or below
the liquidation band the engine flattens the position with a market order and repays the loans,
skimming a fee to the insurance fund. Money is conserved throughout — the trial balance stays zero.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.models import AccountType, MarginLoanStatus, MarginTier, OrderSide, OrderType
from app.services import ledger, margin
from tests.test_trading import make_market, make_user, fund, bal

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def prices(base: str):
    async def _p(symbol: str):
        return {"TBASE": Decimal(base), "TQUOTE": Decimal("1")}.get(symbol)
    return _p


async def mbal(db, user_id, asset_id, wallet, account_type=AccountType.AVAILABLE):
    return (await ledger.get_or_create_account(db, asset_id, account_type, user_id, wallet=wallet)).balance


async def open_long(db):
    """A 5x long: deposit 200 quote, borrow 300, buy 5 base @ 100. Returns (buyer, acct, market)."""
    m = await make_market(db)
    seller = await make_user(db, "liq-seller@example.com")
    buyer = await make_user(db, "liq-buyer@example.com")
    await fund(db, seller, m.base_asset_id, "10")
    await fund(db, buyer, m.quote_asset_id, "1000")
    await trading_sell(db, seller, m, "5", "100")

    acct = await margin.open_account(db, user_id=buyer.id, tier=MarginTier.PRO, leverage=Decimal("5"))
    await margin.transfer_collateral(db, account=acct, asset_id=m.quote_asset_id, amount=Decimal("200"), deposit=True)
    await margin.place_margin_order(db, account=acct, market=m, side=OrderSide.BUY, order_type=OrderType.LIMIT,
                                    quantity=Decimal("5"), price=Decimal("100"), price_of=prices("100"), now=T0)
    return buyer, acct, m


class TestHealth:
    async def test_status_bands(self, db):
        _, acct, m = await open_long(db)
        # base=100 → gross 500, debt 300, level 1.667 → safe
        st = await margin.account_state(db, acct, prices("100"))
        assert margin.health_status(st.margin_level) == "safe"
        # base=72 → gross 360, level 1.2 → margin_call
        st = await margin.account_state(db, acct, prices("72"))
        assert margin.health_status(st.margin_level) == "margin_call"
        # base=64 → gross 320, level 1.067 → liquidatable
        st = await margin.account_state(db, acct, prices("64"))
        assert margin.health_status(st.margin_level) == "liquidatable"


class TestLiquidation:
    async def test_healthy_account_not_liquidated(self, db):
        _, acct, m = await open_long(db)
        did = await margin.liquidate(db, account=acct, market=m, price_of=prices("100"), now=T0)
        assert did is False

    async def test_underwater_long_is_force_closed(self, db):
        buyer, acct, m = await open_long(db)
        # Provide liquidation liquidity: a bidder willing to buy 5 base @ 64.
        bidder = await make_user(db, "liq-bidder@example.com")
        await fund(db, bidder, m.quote_asset_id, "1000")
        await trading_buy(db, bidder, m, "5", "64")

        did = await margin.liquidate(db, account=acct, market=m, price_of=prices("64"), now=T0)
        assert did is True

        # The base position is gone and the quote loan is repaid (or reduced to what the sale covered).
        assert await mbal(db, buyer.id, m.base_asset_id, "MARGIN") == Decimal("0")
        loans = await margin.open_loans(db, acct)
        assert all(ln.asset_id != m.quote_asset_id for ln in loans)  # quote loan closed
        # Money conserved.
        assert (await ledger.trial_balance(db))["TQUOTE"] == Decimal(0)
        assert (await ledger.trial_balance(db))["TBASE"] == Decimal(0)
        # An insurance-fund fee was taken.
        assert (await ledger.get_or_create_account(db, m.quote_asset_id, AccountType.FEE_INCOME)).balance > 0

    async def test_sweep_finds_liquidatable(self, db):
        _, acct, m = await open_long(db)
        # At base=64 the account is liquidatable; the sweep should surface it.
        found = await margin.liquidatable_accounts(db, prices("64"))
        assert acct.id in [a.id for a in found]
        # At base=100 it is safe.
        found = await margin.liquidatable_accounts(db, prices("100"))
        assert acct.id not in [a.id for a in found]


# --- spot maker helpers ---------------------------------------------------------------------------

from app.services import trading  # noqa: E402


async def trading_sell(db, user, market, qty, price):
    return await trading.place_order(db, user_id=user.id, market=market, side=OrderSide.SELL,
                                     order_type=OrderType.LIMIT, quantity=Decimal(qty), price=Decimal(price))


async def trading_buy(db, user, market, qty, price):
    return await trading.place_order(db, user_id=user.id, market=market, side=OrderSide.BUY,
                                     order_type=OrderType.LIMIT, quantity=Decimal(qty), price=Decimal(price))
