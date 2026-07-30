"""Sub-accounts: creation, master-owned transfers, and the money invariant (trial balance zero)."""

from decimal import Decimal

import pytest

from app.models import Asset, AssetKind
from app.services import ledger, subaccounts
from tests.test_trading import bal, fund, make_user


async def make_asset(db, symbol="USDT") -> Asset:
    a = Asset(symbol=symbol, name=symbol, kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def price_of(_s):
    return Decimal("1")


class TestCreate:
    async def test_create_links_to_master(self, db):
        master = await make_user(db, "sa-master@example.com")
        sub = await subaccounts.create(db, master=master, label="Grid Bot")
        assert sub.parent_user_id == master.id and sub.full_name == "Grid Bot"
        subs = await subaccounts.list_subs(db, master.id)
        assert [s.id for s in subs] == [sub.id]

    async def test_sub_cannot_create_sub(self, db):
        master = await make_user(db, "sa-m2@example.com")
        sub = await subaccounts.create(db, master=master, label="Desk")
        with pytest.raises(subaccounts.SubAccountError, match="cannot create"):
            await subaccounts.create(db, master=sub, label="Nested")


class TestTransfer:
    async def test_transfer_in_and_out(self, db):
        usdt = await make_asset(db)
        master = await make_user(db, "sa-xfer@example.com")
        await fund(db, master, usdt.id, "1000")
        sub = await subaccounts.create(db, master=master, label="Bot")

        await subaccounts.transfer(db, master=master, sub_id=sub.id, asset_symbol="USDT", amount=Decimal("300"), to_sub=True)
        assert await bal(db, master.id, usdt.id) == Decimal("700")
        assert await bal(db, sub.id, usdt.id) == Decimal("300")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

        await subaccounts.transfer(db, master=master, sub_id=sub.id, asset_symbol="USDT", amount=Decimal("100"), to_sub=False)
        assert await bal(db, master.id, usdt.id) == Decimal("800")
        assert await bal(db, sub.id, usdt.id) == Decimal("200")

    async def test_cannot_transfer_others_sub(self, db):
        usdt = await make_asset(db)
        m1 = await make_user(db, "sa-a@example.com")
        m2 = await make_user(db, "sa-b@example.com")
        await fund(db, m2, usdt.id, "100")
        sub = await subaccounts.create(db, master=m1, label="A-bot")
        # m2 tries to move funds to m1's sub → refused.
        with pytest.raises(subaccounts.SubAccountError, match="not your sub"):
            await subaccounts.transfer(db, master=m2, sub_id=sub.id, asset_symbol="USDT", amount=Decimal("10"), to_sub=True)

    async def test_insufficient_funds(self, db):
        await make_asset(db)
        master = await make_user(db, "sa-poor@example.com")
        sub = await subaccounts.create(db, master=master, label="Bot")
        with pytest.raises(subaccounts.SubAccountError, match="insufficient"):
            await subaccounts.transfer(db, master=master, sub_id=sub.id, asset_symbol="USDT", amount=Decimal("50"), to_sub=True)
