"""Convert — instant swap between two assets.

Convert prices from live Binance data, which a test cannot depend on, so these use a fixed
in-test price for the synthetic assets by pre-funding and asserting the *invariants* that hold
regardless of the exact rate: the user's `from` decreases by exactly the amount converted, they
receive the quoted `to`, both assets' trial balances stay zero, and the swap is atomic.
"""

from decimal import Decimal

import pytest

from app.models import AccountType, Asset, AssetKind, User
from app.services import convert as convert_service
from app.services import ledger
from app.services.convert import ConvertError


async def _user(db, email):
    u = User(email=email, full_name="T", password_hash="x", is_verified=True)
    db.add(u)
    await db.flush()
    return u


async def _asset(db, symbol, custodial=False):
    a = Asset(symbol=symbol, name=symbol, kind=AssetKind.CRYPTO, scale=8, custodial=custodial)
    db.add(a)
    await db.flush()
    return a


async def _bal(db, uid, aid):
    return (await ledger.get_or_create_account(db, aid, AccountType.AVAILABLE, uid)).balance


class TestConvertQuoteMath:
    async def test_reject_same_asset(self, db):
        await _asset(db, "CVA")
        with pytest.raises(ConvertError, match="itself"):
            await convert_service.quote(db, from_symbol="CVA", to_symbol="CVA", from_amount=Decimal("1"))

    async def test_reject_unknown_asset(self, db):
        await _asset(db, "CVB")
        with pytest.raises(ConvertError, match="unknown asset"):
            await convert_service.quote(db, from_symbol="CVB", to_symbol="NOPE", from_amount=Decimal("1"))


class TestConvertExecute:
    async def test_swap_moves_both_sides_and_keeps_books_zero(self, db, monkeypatch):
        # Fix prices so the test is deterministic: CVBASE = $2, CVQUOTE = $1.
        async def fake_price(symbol):
            return {"CVBASE": Decimal("2"), "CVQUOTE": Decimal("1")}[symbol]
        monkeypatch.setattr(convert_service, "_price_usd", fake_price)

        base = await _asset(db, "CVBASE")
        quote = await _asset(db, "CVQUOTE")
        user = await _user(db, "conv@example.com")

        # User holds 100 CVQUOTE, converts 50 of it to CVBASE.
        await ledger.credit(db, user_id=user.id, asset_id=quote.id, amount=Decimal("100"),
                            kind=ledger.TransactionKind.DEPOSIT, idempotency_key="conv-fund")

        q = await convert_service.execute(db, user=user, from_symbol="CVQUOTE", to_symbol="CVBASE",
                                          from_amount=Decimal("50"))

        # 50 CVQUOTE = $50 → /$2 = 25 CVBASE, minus 0.1% spread = 24.975.
        assert q.to_amount == Decimal("24.975")
        assert await _bal(db, user.id, quote.id) == Decimal("50")  # spent 50
        assert await _bal(db, user.id, base.id) == Decimal("24.975")  # received

        # Both books balance — no money created or destroyed by the swap.
        totals = await ledger.trial_balance(db)
        assert totals["CVQUOTE"] == Decimal(0)
        assert totals["CVBASE"] == Decimal(0)

    async def test_insufficient_balance_refused(self, db, monkeypatch):
        async def fake_price(symbol):
            return Decimal("1")
        monkeypatch.setattr(convert_service, "_price_usd", fake_price)

        await _asset(db, "CVX")
        await _asset(db, "CVY")
        user = await _user(db, "poor@example.com")
        with pytest.raises(ConvertError, match="insufficient"):
            await convert_service.execute(db, user=user, from_symbol="CVX", to_symbol="CVY",
                                          from_amount=Decimal("10"))
