"""Options: premium charged on buy, ITM payout / OTM worthless at expiry, trial balance zero."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import AccountType, Asset, AssetKind, OptionStatus, OptionType
from app.services import ledger, options
from tests.test_trading import make_user

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def price_book(spot="60000"):
    async def _p(symbol: str):
        return Decimal(spot) if symbol.upper() == "BTCUSDT" else None
    return _p


async def usdt(db):
    a = Asset(symbol="USDT", name="USDT", kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def bal(db, uid, aid):
    return (await ledger.get_or_create_account(db, aid, AccountType.AVAILABLE, uid)).balance


async def fund(db, u, a, amount):
    await ledger.credit(db, user_id=u.id, asset_id=a.id, amount=Decimal(amount),
                        kind=ledger.TransactionKind.DEPOSIT, idempotency_key=f"seed:{u.id}:{amount}")


class TestOptions:
    async def test_buy_charges_premium(self, db):
        u = await make_user(db, "opt-buy@example.com")
        a = await usdt(db)
        await fund(db, u, a, "20000")
        pos = await options.buy(db, user_id=u.id, underlying="BTC", type_=OptionType.CALL,
                                strike=Decimal("60000"), size=Decimal("1"), expiry=NOW + timedelta(days=30),
                                now=NOW, price_of=price_book())
        assert pos.premium_paid > 0
        assert await bal(db, u.id, a.id) == Decimal("20000") - pos.premium_paid
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_itm_call_pays_out(self, db):
        u = await make_user(db, "opt-itm@example.com")
        a = await usdt(db)
        await fund(db, u, a, "20000")
        pos = await options.buy(db, user_id=u.id, underlying="BTC", type_=OptionType.CALL,
                                strike=Decimal("60000"), size=Decimal("1"), expiry=NOW + timedelta(days=30),
                                now=NOW, price_of=price_book())
        before = await bal(db, u.id, a.id)
        # Expire with spot 65000 → CALL intrinsic = 5000 payout.
        settled = await options.sweep_expiries(db, now=NOW + timedelta(days=31), price_of=price_book("65000"))
        assert pos.id in settled and pos.status is OptionStatus.EXERCISED and pos.payout == Decimal("5000")
        assert await bal(db, u.id, a.id) == before + Decimal("5000")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_otm_expires_worthless(self, db):
        u = await make_user(db, "opt-otm@example.com")
        a = await usdt(db)
        await fund(db, u, a, "20000")
        pos = await options.buy(db, user_id=u.id, underlying="BTC", type_=OptionType.CALL,
                                strike=Decimal("60000"), size=Decimal("1"), expiry=NOW + timedelta(days=30),
                                now=NOW, price_of=price_book())
        before = await bal(db, u.id, a.id)
        # Expire with spot 55000 → CALL out-of-the-money, no payout.
        await options.sweep_expiries(db, now=NOW + timedelta(days=31), price_of=price_book("55000"))
        assert pos.status is OptionStatus.EXPIRED and pos.payout == Decimal("0")
        assert await bal(db, u.id, a.id) == before   # kept the premium loss only
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_guards(self, db):
        u = await make_user(db, "opt-guard@example.com")
        a = await usdt(db)
        await fund(db, u, a, "20000")
        with pytest.raises(options.OptionError, match="future"):
            await options.buy(db, user_id=u.id, underlying="BTC", type_=OptionType.PUT, strike=Decimal("60000"),
                              size=Decimal("1"), expiry=NOW - timedelta(days=1), now=NOW, price_of=price_book())
