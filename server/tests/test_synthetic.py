"""Synthetic (non-custodial) assets: tradeable but internal-only.

The money-integrity contract for a synthetic asset:
- it is minted into existence (no chain backs it) and can only be traded back for a custodial asset
- it is NOT reconciled against custody (there is nothing on-chain), but
- its trial balance must still be zero — the ledger's per-asset zero-sum still holds.
"""

from decimal import Decimal

from app.models import (
    AccountType,
    Asset,
    AssetKind,
    Market,
    OrderSide,
    OrderType,
    User,
)
from app.services import ledger
from app.services import reconcile as reconcile_service
from app.services import trading


async def _user(db, email):
    u = User(email=email, full_name="T", password_hash="x", is_verified=True)
    db.add(u)
    await db.flush()
    return u


async def test_synthetic_asset_trades_and_stays_internally_consistent(db):
    # A custodial quote (USDT-like) and a synthetic base (DOGE-like, no chain).
    usdt = Asset(symbol="SUSDT", name="q", kind=AssetKind.CRYPTO, scale=8, custodial=True)
    doge = Asset(symbol="SDOGE", name="b", kind=AssetKind.CRYPTO, scale=8, custodial=False)
    db.add_all([usdt, doge])
    await db.flush()
    market = Market(
        symbol="SDOGESUSDT", base_asset_id=doge.id, quote_asset_id=usdt.id,
        price_tick=Decimal("0.00001"), qty_step=Decimal("1"), min_notional=Decimal("1"),
        maker_fee=Decimal(0), taker_fee=Decimal(0), enabled=True,
    )
    db.add(market)
    await db.flush()

    mm = await _user(db, "mm-syn@example.com")
    trader = await _user(db, "trader-syn@example.com")

    # MM minted synthetic DOGE (no deposit — it has no chain); trader funded with quote.
    await ledger.credit(db, user_id=mm.id, asset_id=doge.id, amount=Decimal("1000"),
                        kind=ledger.TransactionKind.ADJUSTMENT, idempotency_key="mint-doge")
    await ledger.credit(db, user_id=trader.id, asset_id=usdt.id, amount=Decimal("100"),
                        kind=ledger.TransactionKind.DEPOSIT, idempotency_key="fund-trader")

    # MM rests an ask; trader buys.
    await trading.place_order(db, user_id=mm.id, market=market, side=OrderSide.SELL,
                              order_type=OrderType.LIMIT, quantity=Decimal("100"), price=Decimal("0.5"))
    await trading.place_order(db, user_id=trader.id, market=market, side=OrderSide.BUY,
                              order_type=OrderType.MARKET, quantity=Decimal("50"))

    # Trader received the synthetic asset; spent quote.
    doge_bal = await ledger.get_or_create_account(db, doge.id, AccountType.AVAILABLE, trader.id)
    assert doge_bal.balance == Decimal("50")

    # Trial balance is zero for BOTH assets — internal consistency holds even for the minted one.
    totals = await ledger.trial_balance(db)
    assert totals["SDOGE"] == Decimal(0)
    assert totals["SUSDT"] == Decimal(0)

    # Reconciliation reports the custodial asset but NOT the synthetic one.
    rec = {r.asset for r in await reconcile_service.reconcile(db)}
    assert "SUSDT" in rec
    assert "SDOGE" not in rec
