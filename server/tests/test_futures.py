"""Futures Stage 1: open/close positions, realized PnL, margin, trial balance zero.

The invariant: money is conserved. Margin is locked on open and released on close; PnL flows to/from
the insurance pool; the fee to FEE_INCOME. Trial balance stays zero through every path.
"""

from decimal import Decimal

import pytest

from app.models import AccountType, Asset, AssetKind, PositionSide, PositionStatus, WALLET_FUTURES
from app.services import futures, ledger
from tests.test_trading import make_user

PRICES = {"BTCUSDT": Decimal("60000")}


def price_book(**overrides):
    book = {**PRICES, **overrides}
    async def _p(symbol: str):
        return book.get(symbol.upper())
    return _p


async def usdt(db) -> Asset:
    a = Asset(symbol="USDT", name="USDT", kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def fbal(db, user_id, asset_id, wallet=WALLET_FUTURES, at=AccountType.AVAILABLE):
    return (await ledger.get_or_create_account(db, asset_id, at, user_id, wallet=wallet)).balance


async def btc(db) -> Asset:
    a = Asset(symbol="BTC", name="Bitcoin", kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def fund_futures(db, user, asset, amount):
    """Credit spot then move to the futures wallet."""
    await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=Decimal(amount),
                        kind=ledger.TransactionKind.DEPOSIT, idempotency_key=f"seed:{user.id}:{asset.symbol}:{amount}")
    await futures.transfer_collateral(db, user_id=user.id, amount=Decimal(amount), deposit=True, asset=asset.symbol)


class TestLong:
    async def test_open_locks_margin(self, db):
        u = await make_user(db, "fut-long@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, "1000")
        # 0.1 BTC @ 60000 = 6000 notional, 10x → 600 margin.
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                          size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())
        assert pos.entry_price == Decimal("60000") and pos.margin == Decimal("600")
        assert await fbal(db, u.id, a.id) == Decimal("400")                       # 1000 - 600 locked
        assert await fbal(db, u.id, a.id, at=AccountType.LOCKED) == Decimal("600")

    async def test_close_in_profit(self, db):
        u = await make_user(db, "fut-long-win@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, "1000")
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                          size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())
        # Price → 61000: PnL = +100. Fee = 6100*0.0004 = 2.44.
        await futures.close_position(db, user_id=u.id, position_id=pos.id, price_of=price_book(BTCUSDT=Decimal("61000")))
        assert pos.status is PositionStatus.CLOSED
        assert pos.realized_pnl == Decimal("100") - Decimal("2.44")
        # Back to available: 400 + margin 600 + pnl 100 - fee 2.44 = 1097.56.
        assert await fbal(db, u.id, a.id) == Decimal("1097.56")
        assert await fbal(db, u.id, a.id, at=AccountType.LOCKED) == Decimal("0")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)


class TestShort:
    async def test_short_profits_when_price_falls(self, db):
        u = await make_user(db, "fut-short@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, "1000")
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.SHORT,
                                          size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())
        # Price → 59000: SHORT PnL = +100. Fee = 5900*0.0004 = 2.36.
        await futures.close_position(db, user_id=u.id, position_id=pos.id, price_of=price_book(BTCUSDT=Decimal("59000")))
        assert pos.realized_pnl == Decimal("100") - Decimal("2.36")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_loss_capped_at_margin(self, db):
        u = await make_user(db, "fut-loss@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, "1000")
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                          size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())
        # Crash to 40000: LONG loss = -2000, far past the 600 margin. User can't go negative — floored.
        await futures.close_position(db, user_id=u.id, position_id=pos.id, price_of=price_book(BTCUSDT=Decimal("40000")))
        assert await fbal(db, u.id, a.id) == Decimal("400")                       # only the un-margined 400 remains
        assert await fbal(db, u.id, a.id, at=AccountType.LOCKED) == Decimal("0")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)             # insurance absorbed the shortfall


class TestLiquidation:
    async def test_liquidation_price_and_sweep(self, db):
        u = await make_user(db, "fut-liq@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, "1000")
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                          size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())
        liq = futures.liquidation_price(pos)   # ~ (60000*0.1 - 600) / (0.1*0.995) ≈ 54271
        assert Decimal("54000") < liq < Decimal("55000")

        # Above liq → not liquidated.
        assert await futures.sweep_liquidations(db, price_book(BTCUSDT=Decimal("58000"))) == []
        assert pos.status is PositionStatus.OPEN

        # Below liq → liquidated, margin gone, trial balance still zero.
        liquidated = await futures.sweep_liquidations(db, price_book(BTCUSDT=Decimal("54000")))
        assert pos.id in liquidated
        assert pos.status is PositionStatus.LIQUIDATED
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)


class TestInverse:
    """COIN-M (coin-margined, inverse): margin + PnL in BTC; size is USD notional."""

    async def test_open_and_close_profit(self, db):
        u = await make_user(db, "coinm-win@example.com")
        b = await btc(db)
        await fund_futures(db, u, b, "1")   # 1 BTC collateral
        # $6000 notional, 10x, entry 60000 → margin = (6000/60000)/10 = 0.01 BTC.
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                          size=Decimal("6000"), leverage=Decimal("10"),
                                          price_of=price_book(), inverse=True)
        assert pos.inverse and pos.margin_asset == "BTC" and pos.margin == Decimal("0.01")
        assert await fbal(db, u.id, b.id, at=AccountType.LOCKED) == Decimal("0.01")

        # Close at 61000: inverse PnL = 6000*(1/60000 - 1/61000) > 0, settled in BTC.
        expect = Decimal("6000") * (Decimal(1) / Decimal("60000") - Decimal(1) / Decimal("61000"))
        assert pos.pnl_at(Decimal("61000")) == expect and expect > 0
        await futures.close_position(db, user_id=u.id, position_id=pos.id,
                                     price_of=price_book(BTCUSDT=Decimal("61000")))
        assert pos.status is PositionStatus.CLOSED
        assert await fbal(db, u.id, b.id, at=AccountType.LOCKED) == Decimal("0")
        assert (await ledger.trial_balance(db))["BTC"] == Decimal(0)

    async def test_short_inverse_and_liquidation(self, db):
        u = await make_user(db, "coinm-liq@example.com")
        b = await btc(db)
        await fund_futures(db, u, b, "1")
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.SHORT,
                                          size=Decimal("6000"), leverage=Decimal("10"),
                                          price_of=price_book(), inverse=True)
        liq = futures.liquidation_price(pos)                 # short liquidates above entry
        assert liq > Decimal("60000")
        # liq_price and should_liquidate must agree: just past liq → liquidated.
        assert futures.should_liquidate(pos, liq + Decimal("100"))
        liquidated = await futures.sweep_liquidations(db, price_book(BTCUSDT=liq + Decimal("100")))
        assert pos.id in liquidated and pos.status is PositionStatus.LIQUIDATED
        assert (await ledger.trial_balance(db))["BTC"] == Decimal(0)


class TestGuards:
    async def test_leverage_and_size_validated(self, db):
        u = await make_user(db, "fut-guard@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, "1000")
        with pytest.raises(futures.FuturesError, match="leverage"):
            await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                        size=Decimal("0.1"), leverage=Decimal("200"), price_of=price_book())
        with pytest.raises(futures.FuturesError, match="size"):
            await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                        size=Decimal("0"), leverage=Decimal("10"), price_of=price_book())

    async def test_insufficient_margin(self, db):
        u = await make_user(db, "fut-poor@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, "100")   # not enough for 600 margin
        with pytest.raises(futures.FuturesError, match="insufficient"):
            await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                        size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())
