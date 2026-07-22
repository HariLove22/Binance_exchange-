"""Ledger operations. Every movement of money goes through here.

Nothing else may write to `accounts`, `ledger_transactions` or `ledger_entries`. Not "should
not" — the invariants only hold if there is one door. A second writer that gets balancing or
locking subtly wrong is exactly the bug that surfaces months later as a balance nobody can
explain.

Three rules this module enforces:

1. **Every posting balances to zero, per asset.** The database checks it at commit too; this
   layer only exposes operations that are balanced by construction.
2. **Everything is idempotent.** A repeat is a no-op, keyed on a caller-supplied string.
3. **Lock before spend.** Funds move AVAILABLE -> LOCKED when an order is placed and only leave
   LOCKED on fill or cancel. Reverse the order and two orders can spend one balance.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AccountType,
    Asset,
    LedgerEntry,
    LedgerTransaction,
    TransactionKind,
)


class LedgerError(Exception):
    """A posting was refused. Safe to surface to a caller."""


class InsufficientFunds(LedgerError):
    def __init__(self, asset: str, requested: Decimal, available: Decimal) -> None:
        super().__init__(f"insufficient {asset}: requested {requested}, available {available}")
        self.asset = asset
        self.requested = requested
        self.available = available


@dataclass(frozen=True)
class Movement:
    """One leg of a posting: put `amount` into `account`. Negative takes it out."""

    account: Account
    amount: Decimal


async def get_or_create_account(
    db: AsyncSession,
    asset_id: int,
    account_type: AccountType,
    user_id: int | None = None,
) -> Account:
    """Fetch an account, creating it on first use.

    Lazy rather than pre-seeded: pre-creating every user × asset × type is tens of thousands of
    empty rows per user, all migrated whenever an asset is listed. The INSERT can lose a race, so
    a unique violation is handled by re-reading — checking first *is* the race.
    """
    stmt = select(Account).where(
        Account.asset_id == asset_id,
        Account.account_type == account_type,
        Account.user_id == user_id if user_id is not None else Account.user_id.is_(None),
    )
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is not None:
        return account

    account = Account(user_id=user_id, asset_id=asset_id, account_type=account_type, balance=Decimal(0))
    db.add(account)
    try:
        # Savepoint so a unique violation does not poison the caller's outer transaction.
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        account = (await db.execute(stmt)).scalar_one()
    return account


async def post(
    db: AsyncSession,
    *,
    idempotency_key: str,
    kind: TransactionKind,
    movements: list[Movement],
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Write one balanced transaction.

    Returns None when `idempotency_key` was already used — the caller is retrying and the work is
    done. That is a success, not an error: treating a retry as failure makes clients retry
    forever, or abandon work that completed.
    """
    existing = (
        await db.execute(
            select(LedgerTransaction).where(LedgerTransaction.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    if not movements:
        raise LedgerError("a transaction needs at least one movement")

    # Checked here for a readable error; the database checks it again at commit, because this
    # invariant must not depend on anyone remembering to call this function.
    totals: dict[int, Decimal] = {}
    for m in movements:
        totals[m.account.asset_id] = totals.get(m.account.asset_id, Decimal(0)) + m.amount
    for asset_id, total in totals.items():
        if total != 0:
            raise LedgerError(f"transaction does not balance: asset {asset_id} sums to {total}")

    txn = LedgerTransaction(idempotency_key=idempotency_key, kind=kind, reference=reference)
    db.add(txn)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        # Two callers raced on the same key; the other won and committed. Same "already done".
        return None

    for m in movements:
        if m.amount == 0:
            raise LedgerError("a zero movement records nothing")
        db.add(
            LedgerEntry(
                transaction_id=txn.id,
                account_id=m.account.id,
                asset_id=m.account.asset_id,
                amount=m.amount,
            )
        )
        m.account.balance = m.account.balance + m.amount
        if m.account.balance < 0 and m.account.account_type not in {
            AccountType.EXTERNAL,
            AccountType.TDS_PAYABLE,
        }:
            raise LedgerError(
                f"account {m.account.id} ({m.account.account_type.value}) would go negative"
            )

    await db.flush()
    return txn


async def credit(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    amount: Decimal,
    kind: TransactionKind,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Move funds into a user's AVAILABLE balance from EXTERNAL.

    EXTERNAL going negative is the design: it is the outside world, so user balances plus EXTERNAL
    always sum to zero, and EXTERNAL's magnitude is what we should be holding on-chain. Reconciling
    those two is how theft and bugs are found.
    """
    if amount <= 0:
        raise LedgerError("credit amount must be positive")

    available = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id)
    external = await get_or_create_account(db, asset_id, AccountType.EXTERNAL)
    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=kind,
        reference=reference,
        movements=[Movement(available, amount), Movement(external, -amount)],
    )


async def lock(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    amount: Decimal,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Reserve funds against an open order: AVAILABLE -> LOCKED.

    Must happen before the order reaches the matching engine, never after. The engine has no
    database and cannot check balances, so an unfunded order reaching it produces a trade the
    ledger cannot settle — after the counterparty has been told they filled. The funds stay the
    user's; they are just not spendable twice.
    """
    if amount <= 0:
        raise LedgerError("lock amount must be positive")

    available = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id)
    locked = await get_or_create_account(db, asset_id, AccountType.LOCKED, user_id)
    if available.balance < amount:
        asset = await db.get(Asset, asset_id)
        raise InsufficientFunds(asset.symbol if asset else str(asset_id), amount, available.balance)

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.ORDER_LOCK,
        reference=reference,
        movements=[Movement(available, -amount), Movement(locked, amount)],
    )


async def unlock(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    amount: Decimal,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Release a reservation on cancel or expiry: LOCKED -> AVAILABLE."""
    if amount <= 0:
        raise LedgerError("unlock amount must be positive")

    available = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id)
    locked = await get_or_create_account(db, asset_id, AccountType.LOCKED, user_id)
    if locked.balance < amount:
        asset = await db.get(Asset, asset_id)
        raise InsufficientFunds(asset.symbol if asset else str(asset_id), amount, locked.balance)

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.ORDER_UNLOCK,
        reference=reference,
        movements=[Movement(locked, -amount), Movement(available, amount)],
    )


async def reserve_withdrawal(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    total: Decimal,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Move funds out of AVAILABLE into PENDING_WITHDRAWAL: AVAILABLE -> PENDING_WITHDRAWAL.

    `total` is amount + fee — the user commits both the moment they request, so neither can be
    spent elsewhere while the withdrawal is in flight. The funds stay the user's (in
    PENDING_WITHDRAWAL) until the chain confirms, which is what lets a failed broadcast refund
    cleanly.
    """
    if total <= 0:
        raise LedgerError("withdrawal total must be positive")

    available = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id)
    pending = await get_or_create_account(db, asset_id, AccountType.PENDING_WITHDRAWAL, user_id)
    if available.balance < total:
        asset = await db.get(Asset, asset_id)
        raise InsufficientFunds(asset.symbol if asset else str(asset_id), total, available.balance)

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.WITHDRAWAL,
        reference=reference,
        movements=[Movement(available, -total), Movement(pending, total)],
    )


async def settle_withdrawal(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    amount: Decimal,
    fee: Decimal,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Finalise a confirmed withdrawal: the amount leaves the system, the fee becomes revenue.

    PENDING_WITHDRAWAL -= amount+fee ; EXTERNAL += amount ; FEE_INCOME += fee. Sums to zero: the
    amount crossing into EXTERNAL is the money that actually left on-chain, and the fee we keep.
    """
    if amount <= 0 or fee < 0:
        raise LedgerError("bad settle amounts")

    pending = await get_or_create_account(db, asset_id, AccountType.PENDING_WITHDRAWAL, user_id)
    external = await get_or_create_account(db, asset_id, AccountType.EXTERNAL)
    movements = [Movement(pending, -(amount + fee)), Movement(external, amount)]
    if fee > 0:
        fee_income = await get_or_create_account(db, asset_id, AccountType.FEE_INCOME)
        movements.append(Movement(fee_income, fee))

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.WITHDRAWAL,
        reference=reference,
        movements=movements,
    )


async def refund_withdrawal(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    total: Decimal,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Return a failed or cancelled withdrawal's funds: PENDING_WITHDRAWAL -> AVAILABLE."""
    if total <= 0:
        raise LedgerError("refund total must be positive")

    pending = await get_or_create_account(db, asset_id, AccountType.PENDING_WITHDRAWAL, user_id)
    available = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id)
    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.WITHDRAWAL,
        reference=reference,
        movements=[Movement(pending, -total), Movement(available, total)],
    )


@dataclass(frozen=True)
class Balance:
    asset_id: int
    symbol: str
    scale: int
    available: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
        return self.available + self.locked


async def balances(db: AsyncSession, user_id: int) -> list[Balance]:
    """Every asset this user holds, spendable and reserved — one query, not one per asset."""
    rows = (
        await db.execute(
            select(Asset, Account.account_type, Account.balance)
            .join(Account, Account.asset_id == Asset.id)
            .where(
                Account.user_id == user_id,
                Account.account_type.in_([AccountType.AVAILABLE, AccountType.LOCKED]),
            )
            .order_by(Asset.symbol)
        )
    ).all()

    merged: dict[int, dict] = {}
    for asset, account_type, balance in rows:
        entry = merged.setdefault(
            asset.id,
            {"symbol": asset.symbol, "scale": asset.scale, "available": Decimal(0), "locked": Decimal(0)},
        )
        if account_type is AccountType.AVAILABLE:
            entry["available"] = balance
        else:
            entry["locked"] = balance

    return [
        Balance(
            asset_id=asset_id,
            symbol=v["symbol"],
            scale=v["scale"],
            available=v["available"],
            locked=v["locked"],
        )
        for asset_id, v in sorted(merged.items(), key=lambda kv: kv[1]["symbol"])
    ]


async def trial_balance(db: AsyncSession) -> dict[str, Decimal]:
    """Sum every entry, grouped by asset. Must be exactly zero for all of them.

    The single most valuable check in the system. A non-zero total means money was created or
    destroyed somewhere — it does not say where, but it says *that*, immediately. Run it
    continuously in production and page a human on any non-zero result.
    """
    rows = (
        await db.execute(
            select(Asset.symbol, func.sum(LedgerEntry.amount))
            .join(LedgerEntry, LedgerEntry.asset_id == Asset.id)
            .group_by(Asset.symbol)
        )
    ).all()
    return {symbol: total or Decimal(0) for symbol, total in rows}
