"""Rewards Hub: task conditions, one-time claim, and the reward credited (trial balance zero)."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models import Asset, AssetKind, KycStatus, User, UserRole
from app.services import kyc, ledger, rewards
from tests.test_trading import bal, fund, make_user

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


async def make_usdt(db) -> Asset:
    a = Asset(symbol="USDT", name="Tether", kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def make_admin(db, email) -> User:
    u = User(email=email, full_name="Admin", password_hash="x", is_verified=True, role=UserRole.ADMIN)
    db.add(u)
    await db.flush()
    return u


class TestTasks:
    async def test_funded_task_completes_when_balance(self, db):
        usdt = await make_usdt(db)
        u = await make_user(db, "rw-fund@example.com")
        st = {t["id"]: t for t in await rewards.status(db, u)}
        assert st["first_deposit"]["completed"] is False
        await fund(db, u, usdt.id, "100")
        st = {t["id"]: t for t in await rewards.status(db, u)}
        assert st["first_deposit"]["completed"] is True

    async def test_kyc_task_tracks_status(self, db):
        await make_usdt(db)
        u = await make_user(db, "rw-kyc@example.com")
        admin = await make_admin(db, "rw-admin@example.com")
        st = {t["id"]: t for t in await rewards.status(db, u)}
        assert st["verify_kyc"]["completed"] is False
        app = await kyc.submit(db, user_id=u.id, legal_name="Jane Doe", date_of_birth=date(1990, 1, 1),
                               country="India", id_type="PASSPORT", id_number="P1234567",
                               doc_front="data:image/png;base64,AAAA")
        await kyc.review(db, admin=admin, application_id=app.id, approve=True, reason=None, now=NOW)
        st = {t["id"]: t for t in await rewards.status(db, u)}
        assert st["verify_kyc"]["completed"] is True


class TestClaim:
    async def test_claim_credits_reward_once(self, db):
        usdt = await make_usdt(db)
        u = await make_user(db, "rw-claim@example.com")
        await fund(db, u, usdt.id, "100")   # completes first_deposit ($2)

        reward = await rewards.claim(db, user=u, task_id="first_deposit", now=NOW)
        assert reward == Decimal("2")
        assert await bal(db, u.id, usdt.id) == Decimal("102")   # 100 + 2 reward
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

        # Second claim is refused.
        with pytest.raises(rewards.RewardError, match="already claimed"):
            await rewards.claim(db, user=u, task_id="first_deposit", now=NOW)

    async def test_cannot_claim_incomplete(self, db):
        await make_usdt(db)
        u = await make_user(db, "rw-incomplete@example.com")
        with pytest.raises(rewards.RewardError, match="not completed"):
            await rewards.claim(db, user=u, task_id="first_trade", now=NOW)

    async def test_unknown_task(self, db):
        await make_usdt(db)
        u = await make_user(db, "rw-unknown@example.com")
        with pytest.raises(rewards.RewardError, match="unknown task"):
            await rewards.claim(db, user=u, task_id="nope", now=NOW)
