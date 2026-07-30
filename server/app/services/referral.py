"""Referral service: codes, sign-up linking, and commission on referees' trading fees.

A user has one stable referral code (generated on first use) and, if they were referred, one
referrer. When a referee pays a trading fee, a fixed share is paid to their referrer out of
FEE_INCOME. Codes are short and unambiguous; the alphabet omits look-alike characters.
"""

import secrets
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, Referral, TransactionKind, User
from app.services import ledger

# Share of a referee's trading fee paid to their referrer.
COMMISSION_RATE = Decimal("0.20")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1


class ReferralError(Exception):
    """A referral action was refused. Safe to surface to a caller."""


def _gen_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


async def get_or_create_code(db: AsyncSession, user: User) -> str:
    """Return the user's referral code, generating and persisting one on first access."""
    if user.referral_code:
        return user.referral_code
    for _ in range(5):  # retry on the astronomically-unlikely collision
        code = _gen_code()
        if (await db.execute(select(User.id).where(User.referral_code == code))).scalar_one_or_none() is None:
            user.referral_code = code
            await db.flush()
            return code
    raise ReferralError("could not allocate a referral code")


async def link_signup(db: AsyncSession, *, referee: User, code: str | None) -> None:
    """On registration, link the new user to the referrer whose code they entered. No-op if the code
    is blank/unknown or would refer the user to themselves."""
    if not code:
        return
    referrer = (await db.execute(select(User).where(User.referral_code == code.upper().strip()))).scalar_one_or_none()
    if referrer is None or referrer.id == referee.id:
        return
    db.add(Referral(referrer_id=referrer.id, referee_id=referee.id, earned_usd=Decimal(0)))
    await db.flush()


async def referrer_of(db: AsyncSession, referee_id: int) -> Referral | None:
    return (await db.execute(select(Referral).where(Referral.referee_id == referee_id))).scalar_one_or_none()


async def pay_commission(
    db: AsyncSession, *, referee_id: int, asset_id: int, fee_amount: Decimal, usd_price: Decimal | None
) -> None:
    """Pay the referee's referrer their share of a fee the referee just paid. No-op if unreferred."""
    if fee_amount <= 0:
        return
    link = await referrer_of(db, referee_id)
    if link is None:
        return
    commission = fee_amount * COMMISSION_RATE
    txn = await ledger.pay_referral(
        db, referrer_id=link.referrer_id, asset_id=asset_id, amount=commission,
        idempotency_key=f"ref:{referee_id}:{asset_id}:{link.id}:{secrets.token_hex(6)}",
        reference=f"referral referee={referee_id}",
    )
    if txn is not None and usd_price is not None:
        link.earned_usd += commission * usd_price


async def summary(db: AsyncSession, user: User) -> dict:
    """Referral dashboard data: the user's code, how many they referred, and total earned (USD)."""
    code = await get_or_create_code(db, user)
    rows = (
        await db.execute(
            select(Referral, User.email).join(User, User.id == Referral.referee_id)
            .where(Referral.referrer_id == user.id).order_by(Referral.id.desc())
        )
    ).all()
    total = sum((r.earned_usd for r, _ in rows), Decimal(0))
    return {
        "code": code,
        "count": len(rows),
        "total_earned_usd": total,
        "commission_rate": COMMISSION_RATE,
        "referrals": [
            {"email": _mask(email), "earned_usd": r.earned_usd, "joined": r.created_at.isoformat()}
            for r, email in rows
        ],
    }


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    shown = name[:2] + "***" if len(name) > 2 else name[0] + "***"
    return f"{shown}@{domain}"
