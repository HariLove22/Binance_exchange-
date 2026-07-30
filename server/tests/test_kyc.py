"""KYC: submit, review, and the transition guards."""

from datetime import date, datetime, timezone

import pytest

from app.models import KycStatus, User, UserRole
from app.services import kyc
from tests.test_trading import make_user

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def make_admin(db, email) -> User:
    u = User(email=email, full_name="Admin", password_hash="x", is_verified=True, role=UserRole.ADMIN)
    db.add(u)
    await db.flush()
    return u


async def submit(db, user):
    return await kyc.submit(
        db, user_id=user.id, legal_name="Jane Doe", date_of_birth=date(1990, 5, 1),
        country="India", id_type="PASSPORT", id_number="P1234567",
    )


class TestSubmit:
    async def test_submit_creates_pending(self, db):
        u = await make_user(db, "kyc-sub@example.com")
        app = await submit(db, u)
        assert app.status is KycStatus.PENDING
        assert (await kyc.get(db, u.id)).legal_name == "Jane Doe"

    async def test_cannot_resubmit_while_pending(self, db):
        u = await make_user(db, "kyc-dupe@example.com")
        await submit(db, u)
        with pytest.raises(kyc.KycError, match="already exists"):
            await submit(db, u)

    async def test_validation(self, db):
        u = await make_user(db, "kyc-bad@example.com")
        with pytest.raises(kyc.KycError, match="ID type"):
            await kyc.submit(db, user_id=u.id, legal_name="Jane Doe", date_of_birth=date(1990, 5, 1),
                             country="India", id_type="BADTYPE", id_number="P1234567")


class TestReview:
    async def test_approve(self, db):
        u = await make_user(db, "kyc-appr@example.com")
        admin = await make_admin(db, "kyc-admin1@example.com")
        app = await submit(db, u)
        reviewed = await kyc.review(db, admin=admin, application_id=app.id, approve=True, reason=None, now=NOW)
        assert reviewed.status is KycStatus.APPROVED
        assert reviewed.reviewed_at == NOW

    async def test_reject_then_resubmit(self, db):
        u = await make_user(db, "kyc-rej@example.com")
        admin = await make_admin(db, "kyc-admin2@example.com")
        app = await submit(db, u)
        await kyc.review(db, admin=admin, application_id=app.id, approve=False, reason="blurry", now=NOW)
        assert app.status is KycStatus.REJECTED and app.reject_reason == "blurry"
        # Rejected user can resubmit → back to pending.
        again = await submit(db, u)
        assert again.status is KycStatus.PENDING and again.reject_reason is None

    async def test_non_admin_cannot_review(self, db):
        u = await make_user(db, "kyc-nonadmin@example.com")
        app = await submit(db, u)
        with pytest.raises(kyc.KycError, match="admin"):
            await kyc.review(db, admin=u, application_id=app.id, approve=True, reason=None, now=NOW)

    async def test_cannot_review_twice(self, db):
        u = await make_user(db, "kyc-twice@example.com")
        admin = await make_admin(db, "kyc-admin3@example.com")
        app = await submit(db, u)
        await kyc.review(db, admin=admin, application_id=app.id, approve=True, reason=None, now=NOW)
        with pytest.raises(kyc.KycError, match="not pending"):
            await kyc.review(db, admin=admin, application_id=app.id, approve=True, reason=None, now=NOW)
