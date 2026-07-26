"""The ledger.

Every test is a specific way money goes missing or gets invented. The database enforces most of
these itself, so several bypass the service and attack the tables directly — an invariant that
only holds when callers behave is not an invariant.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.models import (
    Account,
    AccountType,
    Asset,
    AssetKind,
    LedgerEntry,
    LedgerTransaction,
    TransactionKind,
    User,
)
from app.services import ledger
from app.services.ledger import InsufficientFunds, LedgerError, Movement


async def make_user(db, email: str) -> User:
    user = User(email=email, full_name="Test User", password_hash="x", is_verified=True)
    db.add(user)
    await db.flush()
    return user


async def make_asset(db, symbol: str = "TBTC", scale: int = 8) -> Asset:
    asset = Asset(symbol=symbol, name=f"Test {symbol}", kind=AssetKind.CRYPTO, scale=scale)
    db.add(asset)
    await db.flush()
    return asset


class TestAccounts:
    async def test_creates_on_first_use_and_reuses(self, db):
        user = await make_user(db, "acct@example.com")
        asset = await make_asset(db)
        a = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        b = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        assert a.id == b.id

    async def test_user_cannot_have_two_available_in_one_asset(self, db):
        """Two AVAILABLE in the same asset would let a race spend each."""
        user = await make_user(db, "dupe@example.com")
        asset = await make_asset(db)
        await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        db.add(Account(user_id=user.id, asset_id=asset.id, account_type=AccountType.AVAILABLE, balance=Decimal(0)))
        with pytest.raises(Exception, match="uq_accounts_user_asset_type"):
            await db.flush()

    async def test_system_account_must_not_have_owner(self, db):
        user = await make_user(db, "sys@example.com")
        asset = await make_asset(db)
        db.add(Account(user_id=user.id, asset_id=asset.id, account_type=AccountType.FEE_INCOME, balance=Decimal(0)))
        with pytest.raises(Exception, match="ck_accounts_user_type_consistency"):
            await db.flush()


class TestBalancing:
    async def test_credit_moves_value_from_external(self, db):
        user = await make_user(db, "credit@example.com")
        asset = await make_asset(db)
        await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("1.5"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="dep-1")

        available = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        external = await ledger.get_or_create_account(db, asset.id, AccountType.EXTERNAL)
        assert available.balance == Decimal("1.5")
        # EXTERNAL negative is the design — its magnitude mirrors on-chain holdings.
        assert external.balance == Decimal("-1.5")

    async def test_unbalanced_posting_refused_by_service(self, db):
        user = await make_user(db, "unbal@example.com")
        asset = await make_asset(db)
        account = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        with pytest.raises(LedgerError, match="does not balance"):
            await ledger.post(db, idempotency_key="bad-1", kind=TransactionKind.ADJUSTMENT,
                              movements=[Movement(account, Decimal("10"))])

    async def test_database_rejects_unbalanced_written_directly(self, db):
        """The service is not the only thing that could write. The deferred trigger fires at the
        transaction check, so even a direct write cannot create money."""
        user = await make_user(db, "direct@example.com")
        asset = await make_asset(db)
        account = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)

        txn = LedgerTransaction(idempotency_key="direct-1", kind=TransactionKind.ADJUSTMENT)
        db.add(txn)
        await db.flush()
        db.add(LedgerEntry(transaction_id=txn.id, account_id=account.id, asset_id=asset.id, amount=Decimal("100")))
        await db.flush()  # entry reaches the DB; deferred trigger has not fired yet
        with pytest.raises(Exception, match="does not balance"):
            await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    async def test_trial_balance_zero_for_every_asset(self, db):
        alice = await make_user(db, "alice-tb@example.com")
        bob = await make_user(db, "bob-tb@example.com")
        asset = await make_asset(db)
        await ledger.credit(db, user_id=alice.id, asset_id=asset.id, amount=Decimal("10"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="tb-1")
        await ledger.credit(db, user_id=bob.id, asset_id=asset.id, amount=Decimal("7.25"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="tb-2")
        await ledger.lock(db, user_id=alice.id, asset_id=asset.id, amount=Decimal("4"), idempotency_key="tb-3")
        assert (await ledger.trial_balance(db))[asset.symbol] == Decimal(0)

    async def test_entry_asset_must_match_account(self, db):
        user = await make_user(db, "mismatch@example.com")
        btc = await make_asset(db, "TBTC2")
        usdt = await make_asset(db, "TUSD2", scale=6)
        btc_account = await ledger.get_or_create_account(db, btc.id, AccountType.AVAILABLE, user.id)
        txn = LedgerTransaction(idempotency_key="mm-1", kind=TransactionKind.ADJUSTMENT)
        db.add(txn)
        await db.flush()
        db.add(LedgerEntry(transaction_id=txn.id, account_id=btc_account.id, asset_id=usdt.id, amount=Decimal("1")))
        with pytest.raises(Exception, match="does not match account"):
            await db.flush()


class TestIdempotency:
    async def test_replaying_a_credit_does_not_double_it(self, db):
        user = await make_user(db, "idem@example.com")
        asset = await make_asset(db)
        first = await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("5"),
                                    kind=TransactionKind.DEPOSIT, idempotency_key="same-key")
        second = await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("5"),
                                     kind=TransactionKind.DEPOSIT, idempotency_key="same-key")
        assert first is not None
        assert second is None  # a retry is a success, not an error
        account = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        assert account.balance == Decimal("5")


class TestLocking:
    async def test_lock_moves_available_to_locked(self, db):
        user = await make_user(db, "lock@example.com")
        asset = await make_asset(db)
        await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("10"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="l-1")
        await ledger.lock(db, user_id=user.id, asset_id=asset.id, amount=Decimal("4"), idempotency_key="l-2")
        b = {x.symbol: x for x in await ledger.balances(db, user.id)}[asset.symbol]
        assert b.available == Decimal("6")
        assert b.locked == Decimal("4")
        assert b.total == Decimal("10")

    async def test_two_orders_cannot_lock_same_balance(self, db):
        """The double-spend the whole mechanism prevents."""
        user = await make_user(db, "double@example.com")
        asset = await make_asset(db)
        await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("10"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="d-1")
        await ledger.lock(db, user_id=user.id, asset_id=asset.id, amount=Decimal("10"), idempotency_key="d-2")
        with pytest.raises(InsufficientFunds):
            await ledger.lock(db, user_id=user.id, asset_id=asset.id, amount=Decimal("10"), idempotency_key="d-3")

    async def test_unlock_returns_funds(self, db):
        user = await make_user(db, "unlock@example.com")
        asset = await make_asset(db)
        await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("10"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="u-1")
        await ledger.lock(db, user_id=user.id, asset_id=asset.id, amount=Decimal("4"), idempotency_key="u-2")
        await ledger.unlock(db, user_id=user.id, asset_id=asset.id, amount=Decimal("4"), idempotency_key="u-3")
        b = {x.symbol: x for x in await ledger.balances(db, user.id)}[asset.symbol]
        assert b.available == Decimal("10")
        assert b.locked == Decimal(0)

    async def test_user_balance_cannot_go_negative(self, db):
        user = await make_user(db, "neg@example.com")
        asset = await make_asset(db)
        account = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        external = await ledger.get_or_create_account(db, asset.id, AccountType.EXTERNAL)
        with pytest.raises(LedgerError, match="negative"):
            await ledger.post(db, idempotency_key="neg-1", kind=TransactionKind.ADJUSTMENT,
                              movements=[Movement(account, Decimal("-5")), Movement(external, Decimal("5"))])


class TestAppendOnly:
    async def test_entries_cannot_be_updated(self, db):
        user = await make_user(db, "immutable@example.com")
        asset = await make_asset(db)
        await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("1"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="im-1")
        entry_id = (await db.execute(select(LedgerEntry.id).order_by(LedgerEntry.id.desc()).limit(1))).scalar_one()
        with pytest.raises(Exception, match="append-only"):
            await db.execute(text("UPDATE ledger_entries SET amount = 999 WHERE id = :id"), {"id": entry_id})

    async def test_entries_cannot_be_deleted(self, db):
        user = await make_user(db, "nodelete@example.com")
        asset = await make_asset(db)
        await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("1"),
                            kind=TransactionKind.DEPOSIT, idempotency_key="nd-1")
        entry_id = (await db.execute(select(LedgerEntry.id).order_by(LedgerEntry.id.desc()).limit(1))).scalar_one()
        with pytest.raises(Exception, match="append-only"):
            await db.execute(text("DELETE FROM ledger_entries WHERE id = :id"), {"id": entry_id})


class TestPrecision:
    async def test_full_18_decimal_precision_survives(self, db):
        user = await make_user(db, "precision@example.com")
        asset = await make_asset(db, "TWEI", scale=18)
        amount = Decimal("0.123456789012345678")
        await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=amount,
                            kind=TransactionKind.DEPOSIT, idempotency_key="p-1")
        account = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        assert account.balance == amount

    async def test_many_small_credits_sum_exactly(self, db):
        """0.1 + 0.2 == 0.3 must hold — with floats it does not, and the trial balance drifts."""
        user = await make_user(db, "dust@example.com")
        asset = await make_asset(db, "TDUST", scale=18)
        for i in range(10):
            await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal("0.1"),
                                kind=TransactionKind.DEPOSIT, idempotency_key=f"dust-{i}")
        account = await ledger.get_or_create_account(db, asset.id, AccountType.AVAILABLE, user.id)
        assert account.balance == Decimal("1.0")
        assert (await ledger.trial_balance(db))[asset.symbol] == Decimal(0)
