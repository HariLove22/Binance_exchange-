"""KYC service: submit an application, read status, and (admin) approve or reject.

One application per user. Submitting from a fresh or rejected state creates/updates the row to
PENDING; approve/reject is an operator action. All transitions are guarded so a decided application
can't be silently overwritten by a resubmit unless it was rejected.
"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KycApplication, KycStatus, User, UserRole

ID_TYPES = {"PASSPORT", "NATIONAL_ID", "DRIVERS_LICENSE"}


class KycError(Exception):
    """A KYC action was refused. Safe to surface to a caller."""


async def get(db: AsyncSession, user_id: int) -> KycApplication | None:
    return (await db.execute(select(KycApplication).where(KycApplication.user_id == user_id))).scalar_one_or_none()


async def submit(
    db: AsyncSession,
    *,
    user_id: int,
    legal_name: str,
    date_of_birth: date,
    country: str,
    id_type: str,
    id_number: str,
) -> KycApplication:
    legal_name = legal_name.strip()
    country = country.strip()
    id_number = id_number.strip()
    if len(legal_name) < 2:
        raise KycError("enter your full legal name")
    if id_type not in ID_TYPES:
        raise KycError("unsupported ID type")
    if len(id_number) < 4:
        raise KycError("enter a valid ID number")
    if not country:
        raise KycError("select a country")

    app = await get(db, user_id)
    if app is not None and app.status in (KycStatus.PENDING, KycStatus.APPROVED):
        raise KycError(f"a {app.status.value.lower()} application already exists")

    if app is None:
        app = KycApplication(user_id=user_id)
        db.add(app)
    # Fresh submission (new or after rejection).
    app.legal_name = legal_name
    app.date_of_birth = date_of_birth
    app.country = country
    app.id_type = id_type
    app.id_number = id_number
    app.status = KycStatus.PENDING
    app.reject_reason = None
    app.reviewed_at = None
    await db.flush()
    return app


async def list_pending(db: AsyncSession) -> list[KycApplication]:
    return list(
        (
            await db.execute(
                select(KycApplication).where(KycApplication.status == KycStatus.PENDING).order_by(KycApplication.id.asc())
            )
        ).scalars().all()
    )


async def review(
    db: AsyncSession, *, admin: User, application_id: int, approve: bool, reason: str | None, now: datetime
) -> KycApplication:
    if admin.role is not UserRole.ADMIN:
        raise KycError("only an admin can review KYC")
    app = await db.get(KycApplication, application_id)
    if app is None:
        raise KycError("application not found")
    if app.status is not KycStatus.PENDING:
        raise KycError("application is not pending review")
    app.status = KycStatus.APPROVED if approve else KycStatus.REJECTED
    app.reject_reason = None if approve else (reason or "Did not meet verification requirements")
    app.reviewed_at = now
    return app
