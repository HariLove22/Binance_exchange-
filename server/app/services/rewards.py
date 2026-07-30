"""Rewards Hub service: onboarding tasks, real-state condition checks, and one-time payouts.

Each task pays a small USDT reward when its condition is met and the user claims it. Conditions are
checked against real state — no self-reported progress — and a claim is recorded so it pays once.
Rewards are promotional (credited from EXTERNAL, like a deposit): marketing spend, not backed funds.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Asset,
    MarginAccount,
    Order,
    Referral,
    RewardClaim,
    TransactionKind,
    User,
)
from app.services import kyc, ledger

REWARD_ASSET = "USDT"


class RewardError(Exception):
    """A reward action was refused. Safe to surface to a caller."""


Check = Callable[[AsyncSession, int], Awaitable[bool]]


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    description: str
    reward: Decimal
    check: Check


async def _kyc_done(db: AsyncSession, uid: int) -> bool:
    from app.models import KycStatus
    app = await kyc.get(db, uid)
    return app is not None and app.status is KycStatus.APPROVED


async def _has_traded(db: AsyncSession, uid: int) -> bool:
    return bool((await db.execute(
        select(exists().where(Order.user_id == uid, Order.filled_quantity > 0))
    )).scalar())


async def _funded(db: AsyncSession, uid: int) -> bool:
    return any(b.total > 0 for b in await ledger.balances(db, uid))


async def _referred_someone(db: AsyncSession, uid: int) -> bool:
    return bool((await db.execute(select(exists().where(Referral.referrer_id == uid)))).scalar())


async def _opened_margin(db: AsyncSession, uid: int) -> bool:
    return bool((await db.execute(select(exists().where(MarginAccount.user_id == uid)))).scalar())


TASKS: list[Task] = [
    Task("verify_kyc", "Verify your identity", "Complete KYC verification.", Decimal("5"), _kyc_done),
    Task("first_deposit", "Fund your account", "Have any balance in your wallet.", Decimal("2"), _funded),
    Task("first_trade", "Place your first trade", "Complete a trade on the spot market.", Decimal("10"), _has_traded),
    Task("open_margin", "Open a margin account", "Enable margin trading.", Decimal("3"), _opened_margin),
    Task("refer_friend", "Refer a friend", "Get a friend to sign up with your code.", Decimal("5"), _referred_someone),
]

_BY_ID = {t.id: t for t in TASKS}


async def status(db: AsyncSession, user: User) -> list[dict]:
    """Every task with whether it is completed and already claimed."""
    claimed = set(
        (await db.execute(select(RewardClaim.task_id).where(RewardClaim.user_id == user.id))).scalars().all()
    )
    out = []
    for t in TASKS:
        done = await t.check(db, user.id)
        out.append({"id": t.id, "title": t.title, "description": t.description,
                    "reward": t.reward, "completed": done, "claimed": t.id in claimed})
    return out


async def claim(db: AsyncSession, *, user: User, task_id: str, now: datetime) -> Decimal:
    task = _BY_ID.get(task_id)
    if task is None:
        raise RewardError("unknown task")
    already = (await db.execute(
        select(RewardClaim).where(RewardClaim.user_id == user.id, RewardClaim.task_id == task_id)
    )).scalar_one_or_none()
    if already is not None:
        raise RewardError("already claimed")
    if not await task.check(db, user.id):
        raise RewardError("task not completed yet")

    asset = (await db.execute(select(Asset).where(Asset.symbol == REWARD_ASSET))).scalar_one_or_none()
    if asset is None:
        raise RewardError("reward asset unavailable")

    db.add(RewardClaim(user_id=user.id, task_id=task_id, reward_usdt=task.reward))
    await db.flush()
    await ledger.credit(
        db, user_id=user.id, asset_id=asset.id, amount=task.reward,
        kind=TransactionKind.REWARD, idempotency_key=f"reward:{user.id}:{task_id}",
        reference=f"reward task={task_id}",
    )
    return task.reward


async def total_claimed(db: AsyncSession, user_id: int) -> Decimal:
    return Decimal((await db.execute(
        select(func.coalesce(func.sum(RewardClaim.reward_usdt), 0)).where(RewardClaim.user_id == user_id)
    )).scalar() or 0)
