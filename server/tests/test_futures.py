"""Futures Stage 1: open/close positions, realized PnL, margin, trial balance zero.

The invariant: money is conserved. Margin is locked on open and released on close; PnL flows to/from
the insurance pool; the fee to FEE_INCOME. Trial balance stays zero through every path.
"""

from datetime import datetime, timezone
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


class TestFunding:
    async def _open(self, db, a, email, side):
        u = await make_user(db, email)
        await fund_futures(db, u, a, "1000")
        return await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=side,
                                           size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())

    async def test_long_pays_short_receives(self, db):
        # notional = 0.1 * 60000 = 6000; funding = 6000 * 0.0001 = 0.6 USDT per interval.
        a = await usdt(db)
        longp = await self._open(db, a, "fund-long@example.com", PositionSide.LONG)
        shortp = await self._open(db, a, "fund-short@example.com", PositionSide.SHORT)
        due = datetime.now(timezone.utc) + futures.FUNDING_INTERVAL * 2  # force both due

        funded = await futures.apply_funding(db, now=due, price_of=price_book())
        assert funded == 2

        # long paid 0.6: margin 600 -> 599.4, accrued -0.6
        assert longp.margin == Decimal("599.4") and longp.funding_accrued == Decimal("-0.6")
        # short received 0.6: margin 600 -> 600.6, accrued +0.6
        assert shortp.margin == Decimal("600.6") and shortp.funding_accrued == Decimal("0.6")
        # money conserved
        for asset, total in (await ledger.trial_balance(db)).items():
            assert total == 0, f"{asset} unbalanced: {total}"

    async def test_not_charged_before_interval(self, db):
        a = await usdt(db)
        pos = await self._open(db, a, "fund-early@example.com", PositionSide.LONG)
        # now is only moments after open — nothing is due yet.
        funded = await futures.apply_funding(db, now=datetime.now(timezone.utc), price_of=price_book())
        assert funded == 0 and pos.funding_accrued == Decimal("0")


class TestControls:
    async def _pos(self, db, funds="2000"):
        u = await make_user(db, f"ctrl-{funds}-{Decimal(funds)}@example.com")
        a = await usdt(db)
        await fund_futures(db, u, a, funds)
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                          size=Decimal("0.1"), leverage=Decimal("10"), price_of=price_book())
        return u, a, pos  # margin 600, notional 6000

    async def test_partial_close(self, db):
        u, a, pos = await self._pos(db)
        # Close 0.04 of 0.1 at entry (no PnL). fee = 6000*0.0004*0.4 = 0.96; margin freed 240.
        await futures.close_position(db, user_id=u.id, position_id=pos.id, price_of=price_book(), size=Decimal("0.04"))
        assert pos.status is PositionStatus.OPEN
        assert pos.size == Decimal("0.06") and pos.margin == Decimal("360")
        assert pos.realized_pnl == Decimal("-0.96")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_add_and_remove_margin(self, db):
        u, a, pos = await self._pos(db)
        liq0 = futures.liquidation_price(pos)
        await futures.adjust_margin(db, user_id=u.id, position_id=pos.id, amount=Decimal("100"), add=True, price_of=price_book())
        assert pos.margin == Decimal("700")
        assert futures.liquidation_price(pos) < liq0            # more margin → liq further away
        assert await fbal(db, u.id, a.id, at=AccountType.LOCKED) == Decimal("700")

        await futures.adjust_margin(db, user_id=u.id, position_id=pos.id, amount=Decimal("200"), add=False, price_of=price_book())
        assert pos.margin == Decimal("500")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_remove_too_much_rejected(self, db):
        u, a, pos = await self._pos(db)
        with pytest.raises(futures.FuturesError, match="whole margin"):
            await futures.adjust_margin(db, user_id=u.id, position_id=pos.id, amount=Decimal("600"), add=False, price_of=price_book())
        with pytest.raises(futures.FuturesError, match="liquidate"):
            await futures.adjust_margin(db, user_id=u.id, position_id=pos.id, amount=Decimal("599"), add=False, price_of=price_book())

    async def test_set_leverage_up_frees_margin(self, db):
        u, a, pos = await self._pos(db)
        # 10x -> 20x: required = 6000/20 = 300; 300 released.
        await futures.set_leverage(db, user_id=u.id, position_id=pos.id, leverage=Decimal("20"), price_of=price_book())
        assert pos.leverage == Decimal("20") and pos.margin == Decimal("300")
        assert await fbal(db, u.id, a.id) == Decimal("1700")     # 2000 - 600 + 300 back
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_set_leverage_down_locks_margin(self, db):
        u, a, pos = await self._pos(db)
        # 10x -> 5x: required = 6000/5 = 1200; 600 more locked.
        await futures.set_leverage(db, user_id=u.id, position_id=pos.id, leverage=Decimal("5"), price_of=price_book())
        assert pos.leverage == Decimal("5") and pos.margin == Decimal("1200")
        assert await fbal(db, u.id, a.id, at=AccountType.LOCKED) == Decimal("1200")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)


class TestMarkPrice:
    async def test_mark_smooths_a_wick(self, monkeypatch):
        seq = iter([Decimal("60000"), Decimal("60000"), Decimal("90000")])
        async def fake(sym):
            try:
                return next(seq)
            except StopIteration:
                return Decimal("60000")
        monkeypatch.setattr(futures.marketmaker, "fetch_reference_price", fake)
        futures._mark_ema.pop("BTCUSDT", None)

        assert await futures.mark_price("BTCUSDT") == Decimal("60000")   # seeds to first sample
        await futures.mark_price("BTCUSDT")                              # 60000
        # Last price wicks to 90000 (+50%). Mark = 0.3*90000 + 0.7*60000 = 69000 (+15% only).
        assert await futures.mark_price("BTCUSDT") == Decimal("69000")
        # So a wick that would blow past a liq price on the LAST price barely moves the MARK.


class TestFundingInverse:
    async def test_funding_settles_in_coin(self, db):
        u = await make_user(db, "coinm-fund@example.com")
        b = await btc(db)
        await fund_futures(db, u, b, "1")
        # $6000 notional, 10x → margin 0.01 BTC. notional(mark)=6000/60000=0.1 BTC.
        pos = await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=PositionSide.LONG,
                                          size=Decimal("6000"), leverage=Decimal("10"),
                                          price_of=price_book(), inverse=True)
        due = datetime.now(timezone.utc) + futures.FUNDING_INTERVAL * 2
        assert await futures.apply_funding(db, now=due, price_of=price_book()) == 1
        # funding = 0.1 * 0.0001 = 0.00001 BTC, long pays.
        assert pos.margin == Decimal("0.00999") and pos.funding_accrued == Decimal("-0.00001")
        assert (await ledger.trial_balance(db))["BTC"] == Decimal(0)


class TestNetting:
    async def _u(self, db, email, funds="5000"):
        u = await make_user(db, email)
        a = await usdt(db)
        await fund_futures(db, u, a, funds)
        return u, a

    async def _open(self, db, u, side, size, price):
        return await futures.open_position(db, user_id=u.id, symbol="BTCUSDT", side=side,
                                           size=Decimal(size), leverage=Decimal("10"),
                                           price_of=price_book(BTCUSDT=Decimal(price)))

    async def test_same_side_adds_and_averages(self, db):
        u, a = await self._u(db, "net-add@example.com")
        await self._open(db, u, PositionSide.LONG, "0.1", "60000")   # margin 600
        await self._open(db, u, PositionSide.LONG, "0.1", "62000")   # margin 620
        positions = await futures.open_positions(db, u.id)
        assert len(positions) == 1                                    # netted, not two rows
        p = positions[0]
        assert p.size == Decimal("0.2") and p.entry_price == Decimal("61000") and p.margin == Decimal("1220")

    async def test_opposite_reduces(self, db):
        u, a = await self._u(db, "net-reduce@example.com")
        p = await self._open(db, u, PositionSide.LONG, "0.2", "60000")  # margin 1200
        await self._open(db, u, PositionSide.SHORT, "0.05", "60000")    # reduce by 0.05
        assert p.side is PositionSide.LONG and p.size == Decimal("0.15") and p.margin == Decimal("900")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_opposite_larger_flips(self, db):
        u, a = await self._u(db, "net-flip@example.com")
        longp = await self._open(db, u, PositionSide.LONG, "0.1", "60000")
        await self._open(db, u, PositionSide.SHORT, "0.3", "60000")     # closes long, opens 0.2 short
        assert longp.status is PositionStatus.CLOSED
        positions = await futures.open_positions(db, u.id)
        assert len(positions) == 1 and positions[0].side is PositionSide.SHORT and positions[0].size == Decimal("0.2")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)
