"""Margin foundation: collateral, borrowing under leverage, hourly interest, repayment.

The invariant under all of it: no money is created. Borrowing moves funds from the pool to the user
and back on repay; interest becomes fee income. The trial balance is zero at every step. Leverage is
enforced, and interest accrues by whole elapsed hours.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import (
    AccountType,
    Asset,
    AssetKind,
    MarginLoanStatus,
    MarginMode,
    MarginTier,
    WALLET_SPOT,
)
from app.services import ledger, margin
from tests.test_trading import fund, make_user

# A fixed USD price book so valuation is deterministic.
PRICES = {"USDT": Decimal("1"), "BTC": Decimal("60000"), "ETH": Decimal("3000")}


async def price_of(symbol: str):
    return PRICES.get(symbol)


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def make_asset(db, symbol) -> Asset:
    a = Asset(symbol=symbol, name=symbol, kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def bal(db, user_id, asset_id, wallet=WALLET_SPOT, account_type=AccountType.AVAILABLE):
    acct = await ledger.get_or_create_account(db, asset_id, account_type, user_id, wallet=wallet)
    return acct.balance


class TestAccount:
    async def test_open_defaults_to_cross_classic_3x(self, db):
        u = await make_user(db, "m-open@example.com")
        acct = await margin.open_account(db, user_id=u.id)
        assert acct.mode is MarginMode.CROSS
        assert acct.symbol is None
        assert acct.max_leverage == Decimal("3")
        assert acct.wallet == "MARGIN"

    async def test_leverage_capped_by_tier(self, db):
        u = await make_user(db, "m-lev@example.com")
        with pytest.raises(margin.MarginError, match="between 1x and 3x"):
            await margin.open_account(db, user_id=u.id, tier=MarginTier.CLASSIC, leverage=Decimal("5"))
        # PRO allows up to 20x.
        acct = await margin.open_account(db, user_id=u.id, tier=MarginTier.PRO, leverage=Decimal("10"))
        assert acct.max_leverage == Decimal("10")

    async def test_isolated_needs_symbol_and_caps_10x(self, db):
        u = await make_user(db, "m-iso@example.com")
        acct = await margin.open_account(db, user_id=u.id, mode=MarginMode.ISOLATED, symbol="BTCUSDT",
                                         leverage=Decimal("10"))
        assert acct.wallet == "MARGIN:BTCUSDT"
        with pytest.raises(margin.MarginError, match="1x and 10x"):
            await margin.open_account(db, user_id=u.id, mode=MarginMode.ISOLATED, symbol="ETHUSDT",
                                      leverage=Decimal("11"))


class TestCollateral:
    async def test_transfer_in_and_out(self, db):
        u = await make_user(db, "m-coll@example.com")
        usdt = await make_asset(db, "USDT")
        await fund(db, u, usdt.id, "1000")
        acct = await margin.open_account(db, user_id=u.id)

        await margin.transfer_collateral(db, account=acct, asset_id=usdt.id, amount=Decimal("600"), deposit=True)
        assert await bal(db, u.id, usdt.id) == Decimal("400")                      # spot
        assert await bal(db, u.id, usdt.id, wallet="MARGIN") == Decimal("600")     # margin
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

        await margin.transfer_collateral(db, account=acct, asset_id=usdt.id, amount=Decimal("100"), deposit=False)
        assert await bal(db, u.id, usdt.id) == Decimal("500")
        assert await bal(db, u.id, usdt.id, wallet="MARGIN") == Decimal("500")


class TestBorrow:
    async def _funded_account(self, db, email, collateral="1000"):
        u = await make_user(db, email)
        usdt = await make_asset(db, "USDT")
        await fund(db, u, usdt.id, collateral)
        acct = await margin.open_account(db, user_id=u.id, tier=MarginTier.PRO, leverage=Decimal("5"))
        await margin.transfer_collateral(db, account=acct, asset_id=usdt.id, amount=Decimal(collateral), deposit=True)
        return u, usdt, acct

    async def test_borrow_within_leverage_and_pool_goes_negative(self, db):
        u, usdt, acct = await self._funded_account(db, "m-borrow@example.com")
        # 1000 collateral at 5x → can borrow up to 4000 USD.
        loan = await margin.borrow(db, account=acct, asset_id=usdt.id, amount=Decimal("4000"),
                                   price_of=price_of, now=T0)
        assert loan.principal == Decimal("4000")
        assert await bal(db, u.id, usdt.id, wallet="MARGIN") == Decimal("5000")  # 1000 + 4000 borrowed
        # The pool lent it out → negative.
        pool = await ledger.get_or_create_account(db, usdt.id, AccountType.MARGIN_BORROWED)
        assert pool.balance == Decimal("-4000")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_borrow_over_limit_rejected(self, db):
        _, usdt, acct = await self._funded_account(db, "m-overborrow@example.com")
        with pytest.raises(margin.MarginError, match="exceeds"):
            await margin.borrow(db, account=acct, asset_id=usdt.id, amount=Decimal("4001"),
                                price_of=price_of, now=T0)


class TestInterestAndRepay:
    async def test_interest_accrues_by_whole_hours(self, db):
        u = await make_user(db, "m-int@example.com")
        usdt = await make_asset(db, "USDT")
        await fund(db, u, usdt.id, "1000")
        acct = await margin.open_account(db, user_id=u.id, tier=MarginTier.PRO, leverage=Decimal("5"))
        await margin.transfer_collateral(db, account=acct, asset_id=usdt.id, amount=Decimal("1000"), deposit=True)
        loan = await margin.borrow(db, account=acct, asset_id=usdt.id, amount=Decimal("1000"),
                                   price_of=price_of, hourly_rate=Decimal("0.001"), now=T0)

        # 30 minutes → no whole hour → no interest.
        await margin.accrue_interest(db, now=T0 + timedelta(minutes=30))
        assert loan.accrued_interest == Decimal("0")
        # 3 hours → 1000 * 0.001 * 3 = 3.
        await margin.accrue_interest(db, now=T0 + timedelta(hours=3))
        assert loan.accrued_interest == Decimal("3")

    async def test_repay_clears_interest_then_principal_trial_zero(self, db):
        u = await make_user(db, "m-repay@example.com")
        usdt = await make_asset(db, "USDT")
        await fund(db, u, usdt.id, "1000")
        acct = await margin.open_account(db, user_id=u.id, tier=MarginTier.PRO, leverage=Decimal("5"))
        await margin.transfer_collateral(db, account=acct, asset_id=usdt.id, amount=Decimal("1000"), deposit=True)
        loan = await margin.borrow(db, account=acct, asset_id=usdt.id, amount=Decimal("1000"),
                                   price_of=price_of, hourly_rate=Decimal("0.001"), now=T0)
        await margin.accrue_interest(db, now=T0 + timedelta(hours=10))  # 1000*0.001*10 = 10 interest

        assert loan.owed == Decimal("1010")
        # Margin wallet has 2000 (1000 collateral + 1000 borrowed); repay the full 1010.
        await margin.repay(db, account=acct, loan=loan, amount=Decimal("1010"))
        assert loan.status is MarginLoanStatus.REPAID
        assert loan.owed == Decimal("0")
        # Margin AVAILABLE: 2000 - 1010 = 990.
        assert await bal(db, u.id, usdt.id, wallet="MARGIN") == Decimal("990")
        # Pool restored to zero, interest booked as fee income.
        pool = await ledger.get_or_create_account(db, usdt.id, AccountType.MARGIN_BORROWED)
        assert pool.balance == Decimal("0")
        fee = await ledger.get_or_create_account(db, usdt.id, AccountType.FEE_INCOME)
        assert fee.balance == Decimal("10")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)
