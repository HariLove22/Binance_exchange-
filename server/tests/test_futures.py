"""Futures: position lifecycle, margin lock, PnL, liquidation price.

Invariant under all of it: no money is created. Margin moves spot -> futures on open and back +/-
PnL on close, PnL settling against the pool — so the trial balance is zero at every step.
"""

from decimal import Decimal

import pytest

from app.models import AccountType, PositionSide, PositionStatus, WALLET_FUTURES, WALLET_SPOT
from app.services import futures, ledger
from tests.test_trading import fund, make_market, make_user


async def bal(db, user_id, asset_id, wallet=WALLET_SPOT, account_type=AccountType.AVAILABLE):
    return (await ledger.get_or_create_account(db, asset_id, account_type, user_id, wallet=wallet)).balance


async def assert_books_zero(db):
    for asset, total in (await ledger.trial_balance(db)).items():
        assert total == 0, f"{asset} books don't balance: {total}"


def test_liquidation_price_formulas():
    # 10x, 0.5% MMR: long liquidates ~9.5% below entry, short ~9.5% above.
    assert futures.liquidation_price(PositionSide.LONG, Decimal("60000"), Decimal("10")) == Decimal("54300.000")
    assert futures.liquidation_price(PositionSide.SHORT, Decimal("60000"), Decimal("10")) == Decimal("65700.000")


def test_unrealized_pnl_sign():
    # Long profits when price rises; short profits when it falls. Same move, opposite sign.
    up = (Decimal("60000"), Decimal("66000"), Decimal("0.1"))
    assert futures.unrealized_pnl(PositionSide.LONG, *up) == Decimal("600.0")
    assert futures.unrealized_pnl(PositionSide.SHORT, *up) == Decimal("-600.0")


class TestLifecycle:
    async def _setup(self, db, funds="10000"):
        u = await make_user(db, f"fut-{funds}@example.com")
        m = await make_market(db)
        await fund(db, u, m.quote_asset_id, funds)
        return u, m

    async def test_open_locks_margin(self, db):
        u, m = await self._setup(db)
        pos = await futures.open_position(
            db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
            leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"),
        )
        # notional 6000 / 10x = 600 margin locked in the futures wallet, gone from spot.
        assert pos.margin == Decimal("600.0")
        assert pos.entry_price == Decimal("60000")
        assert pos.liquidation_price == Decimal("54300.000")
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("9400.0")  # 10000 - 600
        assert await bal(db, u.id, m.quote_asset_id, WALLET_FUTURES, AccountType.LOCKED) == Decimal("600.0")
        await assert_books_zero(db)

    async def test_close_in_profit(self, db):
        u, m = await self._setup(db)
        pos = await futures.open_position(
            db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
            leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"),
        )
        pnl = await futures.close_position(db, position=pos, mark_price=Decimal("66000"))
        assert pnl == Decimal("600.0")
        assert pos.status is PositionStatus.CLOSED
        # spent 600 margin, got back margin + 600 profit -> up 600 net.
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("10600.0")
        # pool paid the win: -600.
        assert await bal(db, None, m.quote_asset_id, WALLET_FUTURES, AccountType.FUTURES_POOL) == Decimal("-600.0")
        await assert_books_zero(db)

    async def test_close_in_loss_clamped_to_margin(self, db):
        u, m = await self._setup(db)
        pos = await futures.open_position(
            db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
            leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"),
        )
        # A 20% drop would lose 1200, but the position only risks its 600 margin.
        pnl = await futures.close_position(db, position=pos, mark_price=Decimal("48000"))
        assert pnl == Decimal("-600.0")
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("9400.0")  # margin gone, nothing back
        await assert_books_zero(db)

    async def test_liquidate_sets_status(self, db):
        u, m = await self._setup(db)
        pos = await futures.open_position(
            db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
            leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"),
        )
        await futures.liquidate(db, position=pos, mark_price=pos.liquidation_price)
        assert pos.status is PositionStatus.LIQUIDATED
        await assert_books_zero(db)

    async def test_sweep_liquidates_only_crossed_positions(self, db):
        u, m = await self._setup(db, funds="10000")
        # Long liquidates at 54300; short (from a second account) at 65700.
        long = await futures.open_position(db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
                                           leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"))
        u2 = await make_user(db, "fut-short@example.com")
        await fund(db, u2, m.quote_asset_id, "10000")
        short = await futures.open_position(db, user_id=u2.id, symbol=m.symbol, side=PositionSide.SHORT,
                                            leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"))

        # Price drops to 54000: the long is under its 54300 liq line, the short is not.
        async def price_of(symbol):
            return Decimal("54000")

        liquidated = await futures.sweep_liquidations(db, price_of)
        assert liquidated == [long.id]
        assert long.status is PositionStatus.LIQUIDATED
        assert short.status is PositionStatus.OPEN
        await assert_books_zero(db)

    async def test_full_lifecycle_long_into_liquidation(self, db):
        """Open a 10x long, walk the price around checking PnL, then crash it into liquidation."""
        u, m = await self._setup(db, funds="10000")
        pos = await futures.open_position(db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
                                          leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"))
        assert pos.liquidation_price == Decimal("54300.000")
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("9400.0")  # 600 margin locked away

        # Price up to 63000 -> +300 unrealized, nowhere near liquidation.
        assert futures.unrealized_pnl(pos.side, pos.entry_price, Decimal("63000"), pos.size) == Decimal("300.0")
        assert not futures._should_liquidate(pos.side, Decimal("63000"), pos.liquidation_price)
        # Down to 55000 -> -500, still above the 54300 line.
        assert futures.unrealized_pnl(pos.side, pos.entry_price, Decimal("55000"), pos.size) == Decimal("-500.0")
        assert not futures._should_liquidate(pos.side, Decimal("55000"), pos.liquidation_price)

        # Crash to 54000 -> below the line. The monitor's sweep force-closes it.
        async def price_of(symbol):
            return Decimal("54000")

        assert await futures.sweep_liquidations(db, price_of) == [pos.id]
        assert pos.status is PositionStatus.LIQUIDATED
        assert pos.realized_pnl == Decimal("-600.0")             # loss clamped to the posted margin
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("9400.0")  # margin gone, nothing back
        await assert_books_zero(db)

    async def test_full_lifecycle_short_closed_in_profit(self, db):
        """Open a 10x short, let price fall, close in profit and get margin + PnL back."""
        u, m = await self._setup(db, funds="10000")
        pos = await futures.open_position(db, user_id=u.id, symbol=m.symbol, side=PositionSide.SHORT,
                                          leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"))
        assert pos.liquidation_price == Decimal("65700.000")
        pnl = await futures.close_position(db, position=pos, mark_price=Decimal("57000"))
        assert pnl == Decimal("300.0")
        assert pos.status is PositionStatus.CLOSED
        assert await bal(db, u.id, m.quote_asset_id) == Decimal("10300.0")  # +300 net
        await assert_books_zero(db)

    async def test_rejects_bad_leverage_and_underfunding(self, db):
        u, m = await self._setup(db, funds="100")
        with pytest.raises(futures.FuturesError, match="leverage"):
            await futures.open_position(db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
                                        leverage=Decimal("50"), quantity=Decimal("0.1"), mark_price=Decimal("60000"))
        with pytest.raises(futures.FuturesError, match="insufficient margin"):
            await futures.open_position(db, user_id=u.id, symbol=m.symbol, side=PositionSide.LONG,
                                        leverage=Decimal("10"), quantity=Decimal("0.1"), mark_price=Decimal("60000"))
