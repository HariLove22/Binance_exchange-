"""Internal wallet-to-wallet transfer: funds move between the user's own wallets, money conserved.

The invariant: a transfer only relabels which wallet holds the funds — same user, same asset — so the
trial balance stays zero and nothing is created or destroyed.
"""

from decimal import Decimal

import pytest

from app.models import AccountType, Asset, AssetKind, WALLET_FUTURES, WALLET_MARGIN, WALLET_SPOT
from app.services import ledger
from app.services.ledger import InsufficientFunds, LedgerError
from tests.test_trading import make_user


async def usdt(db) -> Asset:
    a = Asset(symbol="USDT", name="USDT", kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def avail(db, user_id, asset_id, wallet):
    return (await ledger.get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id, wallet=wallet)).balance


async def test_transfer_between_wallets_conserves_money(db):
    u = await make_user(db, "xfer@example.com")
    a = await usdt(db)
    await ledger.credit(db, user_id=u.id, asset_id=a.id, amount=Decimal("1000"),
                        kind=ledger.TransactionKind.DEPOSIT, idempotency_key="seed")

    # Spot -> Futures -> Margin: the money just changes wallets.
    await ledger.transfer_wallet(db, user_id=u.id, asset_id=a.id, amount=Decimal("400"),
                                 from_wallet=WALLET_SPOT, to_wallet=WALLET_FUTURES, idempotency_key="k1")
    await ledger.transfer_wallet(db, user_id=u.id, asset_id=a.id, amount=Decimal("150"),
                                 from_wallet=WALLET_FUTURES, to_wallet=WALLET_MARGIN, idempotency_key="k2")

    assert await avail(db, u.id, a.id, WALLET_SPOT) == Decimal("600")
    assert await avail(db, u.id, a.id, WALLET_FUTURES) == Decimal("250")
    assert await avail(db, u.id, a.id, WALLET_MARGIN) == Decimal("150")
    assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)


async def test_transfer_guards(db):
    u = await make_user(db, "xfer-guard@example.com")
    a = await usdt(db)
    await ledger.credit(db, user_id=u.id, asset_id=a.id, amount=Decimal("10"),
                        kind=ledger.TransactionKind.DEPOSIT, idempotency_key="seed")
    with pytest.raises(LedgerError, match="same"):
        await ledger.transfer_wallet(db, user_id=u.id, asset_id=a.id, amount=Decimal("1"),
                                     from_wallet=WALLET_SPOT, to_wallet=WALLET_SPOT, idempotency_key="g1")
    with pytest.raises(InsufficientFunds):
        await ledger.transfer_wallet(db, user_id=u.id, asset_id=a.id, amount=Decimal("999"),
                                     from_wallet=WALLET_SPOT, to_wallet=WALLET_FUTURES, idempotency_key="g2")
