"""Referral endpoints: the user's code, invite link, and earnings dashboard."""

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services import referral

router = APIRouter(prefix="/referral", tags=["referral"])


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


class ReferralRow(BaseModel):
    email: str
    earned_usd: str
    joined: str


class ReferralSummary(BaseModel):
    code: str
    count: int
    total_earned_usd: str
    commission_rate: str
    referrals: list[ReferralRow]


@router.get("/me", response_model=ReferralSummary)
async def my_referrals(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await referral.summary(db, user)
    await db.commit()  # persist a lazily-generated code
    return ReferralSummary(
        code=s["code"], count=s["count"], total_earned_usd=_n(s["total_earned_usd"]),
        commission_rate=_n(s["commission_rate"] * 100),
        referrals=[ReferralRow(email=r["email"], earned_usd=_n(r["earned_usd"]), joined=r["joined"]) for r in s["referrals"]],
    )
