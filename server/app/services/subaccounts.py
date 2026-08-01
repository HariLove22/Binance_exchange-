"""Sub-accounts: extra accounts a master creates and funds, for separating strategies or desks.

A sub-account is a real user (its own balances and ledger accounts) with `parent_user_id` set to its
master. It cannot log in on its own — the master manages it, moving funds in and out with on-books
internal transfers (zero-sum, no money created). Only the master may act on its own sub-accounts.
"""

import secrets
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import Asset, User
from app.services import ledger


class SubAccountError(Exception):
    """A sub-account action was refused. Safe to surface to a caller."""


async def create(db: AsyncSession, *, master: User, label: str) -> User:
    label = label.strip()
    if len(label) < 2:
        raise SubAccountError("give the sub-account a name")
    if master.parent_user_id is not None:
        raise SubAccountError("a sub-account cannot create sub-accounts")

    # A unique, non-deliverable email and an unknown random password: the sub cannot log in; the
    # master drives it entirely.
    email = f"sub+{master.id}.{secrets.token_hex(4)}@sub.novex.local"
    sub = User(
        email=email, full_name=label, password_hash=hash_password(secrets.token_urlsafe(24)),
        is_verified=True, parent_user_id=master.id,
    )
    db.add(sub)
    await db.flush()
    return sub


async def list_subs(db: AsyncSession, master_id: int) -> list[User]:
    return list(
        (await db.execute(
            select(User).where(User.parent_user_id == master_id).order_by(User.id.asc())
        )).scalars().all()
    )


async def _owned_sub(db: AsyncSession, *, master: User, sub_id: int) -> User:
    sub = await db.get(User, sub_id)
    if sub is None or sub.parent_user_id != master.id:
        raise SubAccountError("not your sub-account")
    return sub


async def transfer(
    db: AsyncSession, *, master: User, sub_id: int, asset_symbol: str, amount: Decimal, to_sub: bool
) -> None:
    """Move funds between the master and one of its sub-accounts."""
    if amount <= 0:
        raise SubAccountError("amount must be positive")
    sub = await _owned_sub(db, master=master, sub_id=sub_id)
    asset = (await db.execute(select(Asset).where(Asset.symbol == asset_symbol.upper()))).scalar_one_or_none()
    if asset is None:
        raise SubAccountError(f"unknown asset {asset_symbol!r}")

    src, dst = (master.id, sub.id) if to_sub else (sub.id, master.id)
    try:
        await ledger.internal_transfer(
            db, from_user_id=src, to_user_id=dst, asset_id=asset.id, amount=amount,
            idempotency_key=f"sub-xfer:{master.id}:{sub.id}:{asset.id}:{'in' if to_sub else 'out'}:{secrets.token_hex(6)}",
            reference=f"sub-account={sub.id}",
        )
    except ledger.InsufficientFunds as exc:
        raise SubAccountError(str(exc)) from exc


async def portfolio_usd(db: AsyncSession, user_id: int, price_of) -> Decimal:
    total = Decimal(0)
    for b in await ledger.balances(db, user_id):
        px = await price_of(b.symbol)
        if px is not None:
            total += b.total * px
    return total
