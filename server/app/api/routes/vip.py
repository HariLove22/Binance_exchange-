"""VIP endpoints: the user's current tier, fees, 30-day volume, and progress to the next tier."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services import vip

router = APIRouter(prefix="/vip", tags=["vip"])


def _pct(rate: Decimal) -> str:
    return f"{(rate * 100).normalize():f}"


class TierRow(BaseModel):
    level: int
    name: str
    min_volume: str
    maker_pct: str
    taker_pct: str


class VipStatus(BaseModel):
    level: int
    name: str
    volume_30d: str
    maker_pct: str
    taker_pct: str
    next_name: str | None
    next_min_volume: str | None
    to_next: str | None       # volume still needed to reach the next tier
    progress: str             # 0..1 toward the next tier
    tiers: list[TierRow]


@router.get("/me", response_model=VipStatus)
async def my_vip(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tier, volume = await vip.user_tier(db, user.id, datetime.now(timezone.utc))
    nxt = vip.next_tier(tier)

    if nxt is None:
        to_next, progress, next_name, next_min = None, "1", None, None
    else:
        span = nxt.min_volume - tier.min_volume
        done = volume - tier.min_volume
        progress = f"{min(Decimal('1'), max(Decimal('0'), done / span)) if span > 0 else Decimal('1'):f}"
        to_next = f"{max(Decimal('0'), nxt.min_volume - volume).normalize():f}"
        next_name, next_min = nxt.name, f"{nxt.min_volume.normalize():f}"

    return VipStatus(
        level=tier.level, name=tier.name, volume_30d=f"{volume.normalize():f}",
        maker_pct=_pct(tier.maker), taker_pct=_pct(tier.taker),
        next_name=next_name, next_min_volume=next_min, to_next=to_next, progress=progress,
        tiers=[TierRow(level=t.level, name=t.name, min_volume=f"{t.min_volume.normalize():f}",
                       maker_pct=_pct(t.maker), taker_pct=_pct(t.taker)) for t in vip.TIERS],
    )
