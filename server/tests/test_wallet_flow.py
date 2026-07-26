"""Deposit and withdrawal flows, at the service level, against the real schema.

Each test is a specific way the flow loses or invents money. The custody edge is mocked; the state
machines, ledger postings, idempotency and reconciliation are real.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    AccountType,
    Asset,
    AssetKind,
    AssetNetwork,
    AddressModel,
    Chain,
    ChainFamily,
    Deposit,
    DepositStatus,
    User,
    Withdrawal,
    WithdrawalStatus,
)
from app.services import deposits as deposit_service
from app.services import ledger
from app.services import reconcile as reconcile_service
from app.services import withdrawals as withdrawal_service
from app.services.withdrawals import WithdrawalError


async def make_user(db, email: str) -> User:
    user = User(email=email, full_name="T", password_hash="x", is_verified=True)
    db.add(user)
    await db.flush()
    return user


async def make_network(db, symbol="TKN", scale=8, decimals=8, fee="1", min_wd="0", chain_code="TCH", evm_id=111) -> AssetNetwork:
    chain = Chain(code=chain_code, name="T", family=ChainFamily.EVM, evm_chain_id=evm_id,
                  native_asset_symbol="ETH", address_model=AddressModel.PER_USER, is_testnet=True)
    asset = Asset(symbol=symbol, name="T", kind=AssetKind.CRYPTO, scale=scale)
    db.add_all([chain, asset])
    await db.flush()
    net = AssetNetwork(asset_id=asset.id, chain_id=chain.id, contract_address=None,
                       onchain_decimals=decimals, confirmations=2, confirmations_large=6,
                       large_threshold=Decimal("10000"), withdrawal_fee=Decimal(fee),
                       min_withdrawal=Decimal(min_wd), deposit_enabled=True, withdraw_enabled=True)
    db.add(net)
    await db.flush()
    return net


async def balance(db, user_id, symbol) -> object:
    return {b.symbol: b for b in await ledger.balances(db, user_id)}.get(symbol)


class TestDepositAddress:
    async def test_same_address_returned_each_time(self, db):
        user = await make_user(db, "addr@example.com")
        net = await make_network(db)
        a = await deposit_service.get_or_create_address(db, user.id, net.id)
        b = await deposit_service.get_or_create_address(db, user.id, net.id)
        assert a.id == b.id
        assert a.address.startswith("0x")  # EVM shape from the mock

    async def test_refused_when_deposits_disabled(self, db):
        user = await make_user(db, "disabled@example.com")
        net = await make_network(db)
        net.deposit_enabled = False
        await db.flush()
        with pytest.raises(deposit_service.DepositError, match="disabled"):
            await deposit_service.get_or_create_address(db, user.id, net.id)


class TestDepositFlow:
    async def _deposit(self, db, user, net, amount, tx="0xabc"):
        addr = await deposit_service.get_or_create_address(db, user.id, net.id)
        d = await deposit_service.record_deposit(db, asset_network_id=net.id, tx_hash=tx, amount=Decimal(amount))
        d.user_id = user.id
        d.deposit_address_id = addr.id
        db.add(d)
        await db.flush()
        return d

    async def test_credits_only_after_enough_confirmations(self, db):
        user = await make_user(db, "conf@example.com")
        net = await make_network(db)  # requires 2 confirmations
        d = await self._deposit(db, user, net, "5")

        d.confirmations = 1
        await deposit_service.credit_if_confirmed(db, d)
        assert d.status is DepositStatus.DETECTED
        assert await balance(db, user.id, net.asset.symbol) is None

        d.confirmations = 2
        await deposit_service.credit_if_confirmed(db, d)
        assert d.status is DepositStatus.CREDITED
        assert (await balance(db, user.id, net.asset.symbol)).available == Decimal("5")

    async def test_large_deposit_needs_more_confirmations(self, db):
        user = await make_user(db, "large@example.com")
        net = await make_network(db)  # large_threshold 10000, large needs 6
        d = await self._deposit(db, user, net, "20000")
        assert d.required_confirmations == 6

    async def test_replayed_deposit_is_not_double_credited(self, db):
        """A webhook fires twice for the same tx. The second must not credit again."""
        user = await make_user(db, "replay@example.com")
        net = await make_network(db)
        d1 = await self._deposit(db, user, net, "5", tx="0xdup")
        d1.confirmations = 2
        await deposit_service.credit_if_confirmed(db, d1)

        # Same (network, tx, vout) → record_deposit returns the existing record, not a new one.
        d2 = await deposit_service.record_deposit(db, asset_network_id=net.id, tx_hash="0xdup", amount=Decimal("5"))
        assert d2.id == d1.id
        assert (await balance(db, user.id, net.asset.symbol)).available == Decimal("5")

    async def test_credit_is_idempotent_even_if_called_twice(self, db):
        user = await make_user(db, "idem-credit@example.com")
        net = await make_network(db)
        d = await self._deposit(db, user, net, "5")
        d.confirmations = 2
        await deposit_service.credit_if_confirmed(db, d)
        await deposit_service.credit_if_confirmed(db, d)  # second call is a no-op
        assert (await balance(db, user.id, net.asset.symbol)).available == Decimal("5")

    async def test_trial_balance_zero_after_deposit(self, db):
        user = await make_user(db, "tb-dep@example.com")
        net = await make_network(db)
        d = await self._deposit(db, user, net, "5")
        d.confirmations = 2
        await deposit_service.credit_if_confirmed(db, d)
        assert (await ledger.trial_balance(db))[net.asset.symbol] == Decimal(0)


async def fund(db, user, net, amount):
    """Credit a user via a deposit so they have something to withdraw."""
    addr = await deposit_service.get_or_create_address(db, user.id, net.id)
    d = await deposit_service.record_deposit(db, asset_network_id=net.id, tx_hash=f"0xfund{user.id}", amount=Decimal(amount))
    d.user_id = user.id
    d.deposit_address_id = addr.id
    d.confirmations = d.required_confirmations
    db.add(d)
    await db.flush()
    await deposit_service.credit_if_confirmed(db, d)


class TestWithdrawalFlow:
    async def test_reserves_amount_plus_fee_on_request(self, db):
        user = await make_user(db, "wd-reserve@example.com")
        net = await make_network(db, fee="1")
        await fund(db, user, net, "100")

        w = await withdrawal_service.request_withdrawal(
            db, user_id=user.id, asset_network_id=net.id, to_address="0xdest", amount=Decimal("40")
        )
        assert w.status is WithdrawalStatus.BROADCAST
        assert w.tx_hash is not None

        b = await balance(db, user.id, net.asset.symbol)
        # 40 + 1 fee reserved out of available.
        assert b.available == Decimal("59")
        # Reserved funds are held in PENDING_WITHDRAWAL, still counted in the user's total? No —
        # `balances` only surfaces AVAILABLE and LOCKED, not PENDING_WITHDRAWAL, so available fell.
        acct = await ledger.get_or_create_account(db, net.asset_id, AccountType.PENDING_WITHDRAWAL, user.id)
        assert acct.balance == Decimal("41")

    async def test_cannot_withdraw_more_than_available(self, db):
        user = await make_user(db, "wd-over@example.com")
        net = await make_network(db, fee="1")
        await fund(db, user, net, "10")
        with pytest.raises(WithdrawalError, match="insufficient"):
            await withdrawal_service.request_withdrawal(
                db, user_id=user.id, asset_network_id=net.id, to_address="0xd", amount=Decimal("10")
            )  # 10 + 1 fee > 10 available

    async def test_confirm_moves_amount_to_external_and_fee_to_income(self, db):
        user = await make_user(db, "wd-confirm@example.com")
        net = await make_network(db, fee="1")
        await fund(db, user, net, "100")
        w = await withdrawal_service.request_withdrawal(
            db, user_id=user.id, asset_network_id=net.id, to_address="0xd", amount=Decimal("40")
        )
        await withdrawal_service.confirm_withdrawal(db, w)
        assert w.status is WithdrawalStatus.CONFIRMED

        # Pending drained; available unchanged (already debited at reserve).
        pending = await ledger.get_or_create_account(db, net.asset_id, AccountType.PENDING_WITHDRAWAL, user.id)
        assert pending.balance == Decimal(0)
        fee_income = await ledger.get_or_create_account(db, net.asset_id, AccountType.FEE_INCOME)
        assert fee_income.balance == Decimal("1")
        assert (await ledger.trial_balance(db))[net.asset.symbol] == Decimal(0)

    async def test_failed_withdrawal_refunds_available(self, db):
        user = await make_user(db, "wd-fail@example.com")
        net = await make_network(db, fee="1")
        await fund(db, user, net, "100")
        w = await withdrawal_service.request_withdrawal(
            db, user_id=user.id, asset_network_id=net.id, to_address="0xd", amount=Decimal("40")
        )
        await withdrawal_service.fail_withdrawal(db, w, reason="test")
        assert w.status is WithdrawalStatus.FAILED
        # Full amount + fee returned to available.
        assert (await balance(db, user.id, net.asset.symbol)).available == Decimal("100")
        assert (await ledger.trial_balance(db))[net.asset.symbol] == Decimal(0)

    async def test_double_submit_deduped_by_idempotency_key(self, db):
        user = await make_user(db, "wd-idem@example.com")
        net = await make_network(db, fee="1")
        await fund(db, user, net, "100")
        w1 = await withdrawal_service.request_withdrawal(
            db, user_id=user.id, asset_network_id=net.id, to_address="0xd", amount=Decimal("10"), idempotency_key="k1"
        )
        w2 = await withdrawal_service.request_withdrawal(
            db, user_id=user.id, asset_network_id=net.id, to_address="0xd", amount=Decimal("10"), idempotency_key="k1"
        )
        assert w1.id == w2.id
        # Only reserved once: 10 + 1 = 11 out of 100.
        assert (await balance(db, user.id, net.asset.symbol)).available == Decimal("89")


class TestReconciliation:
    async def test_ledger_external_matches_custody_after_deposit(self, db):
        user = await make_user(db, "rec-dep@example.com")
        net = await make_network(db, symbol="RECA", chain_code="RCH", evm_id=222)
        await fund(db, user, net, "50")

        rows = {r.asset: r for r in await reconcile_service.reconcile(db)}
        r = rows["RECA"]
        assert r.balanced is True
        # Compare as Decimals — the strings carry full NUMERIC scale ("50.000...").
        assert Decimal(r.ledger_external) == Decimal("50")  # -EXTERNAL
        assert Decimal(r.custody_onchain) == Decimal("50")

    async def test_reconciliation_after_confirmed_withdrawal(self, db):
        user = await make_user(db, "rec-wd@example.com")
        net = await make_network(db, symbol="RECB", fee="1", chain_code="RCH2", evm_id=223)
        await fund(db, user, net, "50")
        w = await withdrawal_service.request_withdrawal(
            db, user_id=user.id, asset_network_id=net.id, to_address="0xd", amount=Decimal("20")
        )
        await withdrawal_service.confirm_withdrawal(db, w)

        rows = {r.asset: r for r in await reconcile_service.reconcile(db)}
        r = rows["RECB"]
        assert r.balanced is True
        # 50 in, 20 out on-chain → 30 held; the 1 fee stayed in the system (FEE_INCOME), not
        # on-chain, so -EXTERNAL is 30 too.
        assert Decimal(r.custody_onchain) == Decimal("30")
        assert Decimal(r.ledger_external) == Decimal("30")
