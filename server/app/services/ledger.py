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
    NEGATIVE_ALLOWED,
    WALLET_SPOT,
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
    wallet: str = WALLET_SPOT,
) -> Account:
    """Fetch an account, creating it on first use.

    Lazy rather than pre-seeded: pre-creating every user × asset × type is tens of thousands of
    empty rows per user, all migrated whenever an asset is listed. The INSERT can lose a race, so
    a unique violation is handled by re-reading — checking first *is* the race.

    `wallet` selects the sub-wallet (SPOT by default, MARGIN / MARGIN:{symbol} for margin). Spot and
    margin balances of the same asset are different accounts.
    """
    stmt = select(Account).where(
        Account.asset_id == asset_id,
        Account.account_type == account_type,
        Account.wallet == wallet,
        Account.user_id == user_id if user_id is not None else Account.user_id.is_(None),
    )
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is not None:
        return account

    account = Account(
        user_id=user_id, asset_id=asset_id, account_type=account_type, wallet=wallet, balance=Decimal(0)
    )
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
        if m.account.balance < 0 and m.account.account_type not in NEGATIVE_ALLOWED:
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
    wallet: str = WALLET_SPOT,
) -> LedgerTransaction | None:
    """Reserve funds against an open order: AVAILABLE -> LOCKED, within one sub-wallet.

    Must happen before the order reaches the matching engine, never after. The engine has no
    database and cannot check balances, so an unfunded order reaching it produces a trade the
    ledger cannot settle — after the counterparty has been told they filled. The funds stay the
    user's; they are just not spendable twice. `wallet` keeps a margin order's lock off spot funds.
    """
    if amount <= 0:
        raise LedgerError("lock amount must be positive")

    available = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=wallet)
    locked = await get_or_create_account(db, asset_id, AccountType.LOCKED, user_id, wallet=wallet)
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
    wallet: str = WALLET_SPOT,
) -> LedgerTransaction | None:
    """Release a reservation on cancel or expiry: LOCKED -> AVAILABLE, within one sub-wallet."""
    if amount <= 0:
        raise LedgerError("unlock amount must be positive")

    available = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=wallet)
    locked = await get_or_create_account(db, asset_id, AccountType.LOCKED, user_id, wallet=wallet)
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


async def settle_trade(
    db: AsyncSession,
    *,
    base_asset_id: int,
    quote_asset_id: int,
    buyer_id: int,
    seller_id: int,
    price: Decimal,
    quantity: Decimal,
    buyer_fee: Decimal,
    seller_fee: Decimal,
    idempotency_key: str,
    reference: str | None = None,
    buyer_wallet: str = WALLET_SPOT,
    seller_wallet: str = WALLET_SPOT,
) -> LedgerTransaction | None:
    """Settle one fill: the buyer gets base, the seller gets quote, each pays a fee on what they
    receive. Both sides' funds are already LOCKED (buyer's quote, seller's base).

        quote (buyer.LOCKED -> seller.AVAILABLE, minus seller's fee to FEE_INCOME)
        base  (seller.LOCKED -> buyer.AVAILABLE, minus buyer's fee to FEE_INCOME)

    Sums to zero in each asset independently. Fees are taken from the received side, exactly as
    Binance does — the buyer pays their fee in base, the seller in quote. Each side settles in its
    own wallet, so a margin taker and a spot maker fill against each other cleanly.
    """
    quote_amount = price * quantity

    buyer_quote_locked = await get_or_create_account(db, quote_asset_id, AccountType.LOCKED, buyer_id, wallet=buyer_wallet)
    seller_quote_avail = await get_or_create_account(db, quote_asset_id, AccountType.AVAILABLE, seller_id, wallet=seller_wallet)
    seller_base_locked = await get_or_create_account(db, base_asset_id, AccountType.LOCKED, seller_id, wallet=seller_wallet)
    buyer_base_avail = await get_or_create_account(db, base_asset_id, AccountType.AVAILABLE, buyer_id, wallet=buyer_wallet)

    movements = [
        Movement(buyer_quote_locked, -quote_amount),
        Movement(seller_quote_avail, quote_amount - seller_fee),
        Movement(seller_base_locked, -quantity),
        Movement(buyer_base_avail, quantity - buyer_fee),
    ]
    if seller_fee > 0:
        movements.append(Movement(await get_or_create_account(db, quote_asset_id, AccountType.FEE_INCOME), seller_fee))
    if buyer_fee > 0:
        movements.append(Movement(await get_or_create_account(db, base_asset_id, AccountType.FEE_INCOME), buyer_fee))

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.TRADE,
        reference=reference,
        movements=movements,
    )


async def p2p_release_escrow(
    db: AsyncSession,
    *,
    seller_id: int,
    buyer_id: int,
    asset_id: int,
    amount: Decimal,
    fee: Decimal = Decimal(0),
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Release P2P escrow: the seller's LOCKED crypto goes to the buyer's AVAILABLE.

    The fiat leg settles off-platform between the two people, so only the crypto moves on our books.
    An optional platform fee is skimmed to FEE_INCOME. Balances to zero in the crypto asset:
    seller.LOCKED -= amount ; buyer.AVAILABLE += amount - fee ; FEE_INCOME += fee.
    """
    if amount <= 0:
        raise LedgerError("release amount must be positive")
    if fee < 0 or fee >= amount:
        raise LedgerError("fee must be non-negative and less than the amount")

    seller_locked = await get_or_create_account(db, asset_id, AccountType.LOCKED, seller_id)
    buyer_avail = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, buyer_id)
    if seller_locked.balance < amount:
        asset = await db.get(Asset, asset_id)
        raise InsufficientFunds(asset.symbol if asset else str(asset_id), amount, seller_locked.balance)

    movements = [Movement(seller_locked, -amount), Movement(buyer_avail, amount - fee)]
    if fee > 0:
        movements.append(Movement(await get_or_create_account(db, asset_id, AccountType.FEE_INCOME), fee))

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.TRADE,
        reference=reference,
        movements=movements,
    )


async def transfer_wallet(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    amount: Decimal,
    from_wallet: str,
    to_wallet: str,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Move a user's AVAILABLE funds from one sub-wallet to another (e.g. spot -> margin collateral).

    Same asset, same user, both AVAILABLE — so it balances to zero. This is how collateral enters and
    leaves a margin account without ever leaving the user's ownership.
    """
    if amount <= 0:
        raise LedgerError("transfer amount must be positive")
    if from_wallet == to_wallet:
        raise LedgerError("source and destination wallets are the same")

    src = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=from_wallet)
    dst = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=to_wallet)
    if src.balance < amount:
        asset = await db.get(Asset, asset_id)
        raise InsufficientFunds(asset.symbol if asset else str(asset_id), amount, src.balance)

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.MARGIN_TRANSFER,
        reference=reference,
        movements=[Movement(src, -amount), Movement(dst, amount)],
    )


async def margin_borrow(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    amount: Decimal,
    wallet: str,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Lend a margin borrower funds: their MARGIN AVAILABLE += amount, the pool goes negative.

    The MARGIN_BORROWED pool is the exchange's lent-out liability in this asset; its magnitude is the
    outstanding principal. Balances to zero — nothing is minted, the pool simply owes it out.
    """
    if amount <= 0:
        raise LedgerError("borrow amount must be positive")

    borrower = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=wallet)
    pool = await get_or_create_account(db, asset_id, AccountType.MARGIN_BORROWED)
    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.MARGIN_BORROW,
        reference=reference,
        movements=[Movement(pool, -amount), Movement(borrower, amount)],
    )


async def margin_repay(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    principal: Decimal,
    interest: Decimal,
    wallet: str,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Repay a margin loan: principal returns to the pool, interest becomes fee income.

    MARGIN AVAILABLE -= principal+interest ; pool += principal ; FEE_INCOME += interest. Balances to
    zero: the principal the pool lent comes back, and the interest is what the exchange earned.
    """
    if principal < 0 or interest < 0 or principal + interest <= 0:
        raise LedgerError("bad repay amounts")

    borrower = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=wallet)
    total = principal + interest
    if borrower.balance < total:
        asset = await db.get(Asset, asset_id)
        raise InsufficientFunds(asset.symbol if asset else str(asset_id), total, borrower.balance)

    pool = await get_or_create_account(db, asset_id, AccountType.MARGIN_BORROWED)
    movements = [Movement(borrower, -total), Movement(pool, principal)]
    if interest > 0:
        movements.append(Movement(await get_or_create_account(db, asset_id, AccountType.FEE_INCOME), interest))

    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.MARGIN_INTEREST if interest > 0 else TransactionKind.MARGIN_BORROW,
        reference=reference,
        movements=movements,
    )


async def internal_transfer(
    db: AsyncSession,
    *,
    from_user_id: int,
    to_user_id: int,
    asset_id: int,
    amount: Decimal,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Move AVAILABLE funds from one user to another (e.g. master ↔ sub-account). Zero-sum, on-books."""
    if amount <= 0:
        raise LedgerError("transfer amount must be positive")
    if from_user_id == to_user_id:
        raise LedgerError("cannot transfer to the same account")
    src = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, from_user_id)
    if src.balance < amount:
        asset = await db.get(Asset, asset_id)
        raise InsufficientFunds(asset.symbol if asset else str(asset_id), amount, src.balance)
    dst = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, to_user_id)
    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.ADJUSTMENT,
        reference=reference,
        movements=[Movement(src, -amount), Movement(dst, amount)],
    )


async def pay_referral(
    db: AsyncSession,
    *,
    referrer_id: int,
    asset_id: int,
    amount: Decimal,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Pay a referrer their commission out of FEE_INCOME: FEE_INCOME -= amount ; referrer += amount.

    Real money leaving the exchange's revenue into the referrer's spendable balance, balanced to zero
    in the fee asset. Skips silently if FEE_INCOME lacks the funds (nothing to share)."""
    if amount <= 0:
        return None
    fee_income = await get_or_create_account(db, asset_id, AccountType.FEE_INCOME)
    if fee_income.balance < amount:
        amount = fee_income.balance
    if amount <= 0:
        return None
    referrer = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, referrer_id)
    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=TransactionKind.REFERRAL,
        reference=reference,
        movements=[Movement(fee_income, -amount), Movement(referrer, amount)],
    )


async def futures_close(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    margin: Decimal,
    pnl: Decimal,
    fee: Decimal,
    wallet: str,
    idempotency_key: str,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Settle a closed futures position: release margin, apply PnL vs the insurance pool, take the fee.

    The user receives max(0, margin + pnl - fee); the insurance pool nets the rest (it pays profits,
    absorbs losses). Balanced to zero in the settlement asset by construction.
    ponytail: user_out is floored at 0 — a loss past the margin is bad debt the pool eats. Liquidation
    (Stage 2) keeps that from happening in practice.
    """
    locked = await get_or_create_account(db, asset_id, AccountType.LOCKED, user_id, wallet=wallet)
    avail = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=wallet)
    insurance = await get_or_create_account(db, asset_id, AccountType.FUTURES_INSURANCE)

    user_out = max(Decimal(0), margin + pnl - fee)
    insurance_delta = margin - user_out - fee   # makes the whole posting sum to zero

    movements = [Movement(locked, -margin)]
    if user_out > 0:
        movements.append(Movement(avail, user_out))
    if fee > 0:
        movements.append(Movement(await get_or_create_account(db, asset_id, AccountType.FEE_INCOME), fee))
    if insurance_delta != 0:
        movements.append(Movement(insurance, insurance_delta))

    return await post(
        db, idempotency_key=idempotency_key, kind=TransactionKind.TRADE, reference=reference, movements=movements,
    )


async def collect_fee(
    db: AsyncSession,
    *,
    user_id: int,
    asset_id: int,
    amount: Decimal,
    wallet: str,
    idempotency_key: str,
    kind: TransactionKind = TransactionKind.FEE,
    reference: str | None = None,
) -> LedgerTransaction | None:
    """Take a fee from a user's AVAILABLE (in `wallet`) into FEE_INCOME. Used for liquidation fees."""
    if amount <= 0:
        raise LedgerError("fee amount must be positive")
    src = await get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=wallet)
    if src.balance < amount:
        amount = src.balance  # never take more than is there; the insurance fund covers any shortfall
    if amount <= 0:
        return None
    fee_income = await get_or_create_account(db, asset_id, AccountType.FEE_INCOME)
    return await post(
        db,
        idempotency_key=idempotency_key,
        kind=kind,
        reference=reference,
        movements=[Movement(src, -amount), Movement(fee_income, amount)],
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


async def balances(db: AsyncSession, user_id: int, wallet: str = WALLET_SPOT) -> list[Balance]:
    """Every asset this user holds in one wallet, spendable and reserved — one query, not one per
    asset. Defaults to the SPOT wallet so margin/demo funds never leak into the spot view."""
    rows = (
        await db.execute(
            select(Asset, Account.account_type, Account.balance)
            .join(Account, Account.asset_id == Asset.id)
            .where(
                Account.user_id == user_id,
                Account.wallet == wallet,
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
