"""KYC endpoints: submit and read your own application; admin lists and reviews pending ones."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_user, get_current_user
from app.core.db import get_db
from app.models import KycStatus, User
from app.services import kyc
from app.services.kyc import KycError

router = APIRouter(prefix="/kyc", tags=["kyc"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SubmitRequest(BaseModel):
    legal_name: str
    date_of_birth: date
    country: str
    id_type: str
    id_number: str
    # Base64 image data URIs; the client downscales before sending.
    doc_front: str | None = None
    doc_back: str | None = None
    selfie: str | None = None


class KycResponse(BaseModel):
    status: str  # NOT_STARTED / PENDING / APPROVED / REJECTED
    legal_name: str | None = None
    country: str | None = None
    id_type: str | None = None
    reject_reason: str | None = None
    submitted_at: str | None = None
    reviewed_at: str | None = None
    has_front: bool = False
    has_back: bool = False
    has_selfie: bool = False


def _resp(app) -> KycResponse:
    if app is None:
        return KycResponse(status=KycStatus.NOT_STARTED.value)
    return KycResponse(
        status=app.status.value, legal_name=app.legal_name, country=app.country, id_type=app.id_type,
        reject_reason=app.reject_reason,
        submitted_at=app.submitted_at.isoformat() if app.submitted_at else None,
        reviewed_at=app.reviewed_at.isoformat() if app.reviewed_at else None,
        has_front=app.doc_front is not None, has_back=app.doc_back is not None, has_selfie=app.selfie is not None,
    )


@router.get("/me", response_model=KycResponse)
async def my_kyc(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _resp(await kyc.get(db, user.id))


@router.post("/submit", response_model=KycResponse, status_code=status.HTTP_201_CREATED)
async def submit(body: SubmitRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        app = await kyc.submit(
            db, user_id=user.id, legal_name=body.legal_name, date_of_birth=body.date_of_birth,
            country=body.country, id_type=body.id_type, id_number=body.id_number,
            doc_front=body.doc_front, doc_back=body.doc_back, selfie=body.selfie,
        )
    except KycError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _resp(app)


# --- admin ----------------------------------------------------------------------------------------

class PendingRow(BaseModel):
    id: int
    user_id: int
    email: str
    legal_name: str
    date_of_birth: str
    country: str
    id_type: str
    id_number: str
    submitted_at: str


class ReviewRequest(BaseModel):
    approve: bool
    reason: str | None = None


class KycDetail(PendingRow):
    """Full application for the admin detail view, including the uploaded document images."""
    doc_front: str | None = None
    doc_back: str | None = None
    selfie: str | None = None


@router.get("/admin/pending", response_model=list[PendingRow], dependencies=[Depends(admin_user)])
async def pending(db: AsyncSession = Depends(get_db)):
    apps = await kyc.list_pending(db)
    rows: list[PendingRow] = []
    for a in apps:
        u = await db.get(User, a.user_id)
        rows.append(PendingRow(
            id=a.id, user_id=a.user_id, email=u.email if u else "?", legal_name=a.legal_name,
            date_of_birth=a.date_of_birth.isoformat(), country=a.country, id_type=a.id_type,
            id_number=a.id_number, submitted_at=a.submitted_at.isoformat(),
        ))
    return rows


@router.get("/admin/{application_id}", response_model=KycDetail, dependencies=[Depends(admin_user)])
async def detail(application_id: int, db: AsyncSession = Depends(get_db)):
    """One application with its uploaded documents, for the operator to inspect before deciding."""
    from app.models import KycApplication
    a = await db.get(KycApplication, application_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    u = await db.get(User, a.user_id)
    return KycDetail(
        id=a.id, user_id=a.user_id, email=u.email if u else "?", legal_name=a.legal_name,
        date_of_birth=a.date_of_birth.isoformat(), country=a.country, id_type=a.id_type,
        id_number=a.id_number, submitted_at=a.submitted_at.isoformat(),
        doc_front=a.doc_front, doc_back=a.doc_back, selfie=a.selfie,
    )


@router.post("/admin/{application_id}/review", response_model=KycResponse)
async def review(application_id: int, body: ReviewRequest, admin: User = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    try:
        app = await kyc.review(db, admin=admin, application_id=application_id, approve=body.approve, reason=body.reason, now=_now())
    except KycError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _resp(app)
