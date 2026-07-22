"""Ledger service — the only place that moves money.

Everything goes through `post_transaction`, which refuses to write anything that doesn't
balance to zero per asset. That single check is what makes "money was created" impossible
rather than merely unlikely.

Concurrency: accounts are locked with SELECT ... FOR UPDATE before their balance is touched.
That's the correct starting point (fine to ~5-10k TPS/row); the scaling ladder beyond it is
optimistic versioning, then a single-writer actor per account.
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.wallet import (
    AVAILABLE,
    LOCKED,
    Account,
    LedgerEntry,
    Transaction,
)


class LedgerError(Exception):
    """Raised when a transaction would break an invariant."""


async def get_or_create_account(
    db: AsyncSession, *, asset: str, account_type: str, user_id: int | None = None
) -> Account:
    stmt = select(Account).where(
        Account.asset == asset,
        Account.account_type == account_type,
        Account.user_id.is_(None) if user_id is None else Account.user_id == user_id,
    )
    account = await db.scalar(stmt)
    if account is not None:
        return account

    account = Account(user_id=user_id, asset=asset, account_type=account_type, balance=0)
    db.add(account)
    try:
        await db.flush()
    except IntegrityError:
        # Lost the race with a concurrent creator — take theirs.
        await db.rollback()
        account = await db.scalar(stmt)
        if account is None:  # pragma: no cover - only if the row vanished
            raise LedgerError(f"could not create account {asset}/{account_type}")
    return account


async def post_transaction(
    db: AsyncSession,
    *,
    kind: str,
    idempotency_key: str,
    legs: list[tuple[Account, int]],
) -> Transaction:
    """Write one balanced transaction.

    `legs` is a list of (account, signed_amount). Debits are negative, credits positive.
    Every asset touched must sum to exactly zero across the legs.
    """
    if not legs:
        raise LedgerError("a transaction needs at least one leg")

    totals: dict[str, int] = defaultdict(int)
    for account, amount in legs:
        if amount == 0:
            raise LedgerError("a ledger entry cannot be zero")
        totals[account.asset] += amount

    unbalanced = {a: t for a, t in totals.items() if t != 0}
    if unbalanced:
        raise LedgerError(f"transaction does not balance to zero: {unbalanced}")

    txn = Transaction(kind=kind, idempotency_key=idempotency_key)
    db.add(txn)
    await db.flush()

    # Lock the touched accounts (stable order by id, so concurrent transactions touching the
    # same pair can't deadlock by grabbing them in opposite orders).
    ids = sorted({a.id for a, _ in legs})
    locked = (
        await db.scalars(select(Account).where(Account.id.in_(ids)).with_for_update().order_by(Account.id))
    ).all()
    by_id = {a.id: a for a in locked}

    for account, amount in legs:
        row = by_id[account.id]
        new_balance = row.balance + amount
        # User-held balances can never go negative. System accounts (EXTERNAL) are expected to.
        if row.user_id is not None and row.account_type in (AVAILABLE, LOCKED) and new_balance < 0:
            raise LedgerError(
                f"insufficient {row.asset}: balance {row.balance}, requested change {amount}"
            )
        row.balance = new_balance
        db.add(LedgerEntry(transaction_id=txn.id, account_id=row.id, asset=row.asset, amount=amount))

    await db.flush()
    return txn


async def get_balances(db: AsyncSession, user_id: int) -> dict[str, dict[str, int]]:
    """Return {asset: {"available": int, "locked": int}} for one user."""
    rows = (
        await db.scalars(
            select(Account).where(
                Account.user_id == user_id, Account.account_type.in_((AVAILABLE, LOCKED))
            )
        )
    ).all()

    out: dict[str, dict[str, int]] = defaultdict(lambda: {"available": 0, "locked": 0})
    for row in rows:
        key = "available" if row.account_type == AVAILABLE else "locked"
        out[row.asset][key] = row.balance
    return dict(out)
