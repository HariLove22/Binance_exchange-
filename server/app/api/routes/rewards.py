"""Rewards Hub endpoints: task list with progress, and claiming a completed task's reward."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services import rewards
from app.services.rewards import RewardError

router = APIRouter(prefix="/rewards", tags=["rewards"])


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


class TaskRow(BaseModel):
    id: str
    title: str
    description: str
    reward: str
    completed: bool
    claimed: bool


class RewardsResponse(BaseModel):
    total_claimed: str
    reward_asset: str
    tasks: list[TaskRow]


class ClaimRequest(BaseModel):
    task_id: str


async def _response(db: AsyncSession, user: User) -> RewardsResponse:
    tasks = await rewards.status(db, user)
    total = await rewards.total_claimed(db, user.id)
    return RewardsResponse(
        total_claimed=_n(total), reward_asset=rewards.REWARD_ASSET,
        tasks=[TaskRow(id=t["id"], title=t["title"], description=t["description"],
                       reward=_n(t["reward"]), completed=t["completed"], claimed=t["claimed"]) for t in tasks],
    )


@router.get("/me", response_model=RewardsResponse)
async def my_rewards(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _response(db, user)


@router.post("/claim", response_model=RewardsResponse)
async def claim(body: ClaimRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await rewards.claim(db, user=user, task_id=body.task_id, now=datetime.now(timezone.utc))
    except RewardError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _response(db, user)
