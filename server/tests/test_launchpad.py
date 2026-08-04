"""Token launchpad: create a coin, run an offering, list on an AMM pool, swap. Money conserved.

The invariant across every path: the double-entry ledger nets to zero per asset. A mint credits the
creator from EXTERNAL; a sale/swap only moves funds between users; so trial balance stays zero.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import AccountType, Asset, AssetKind, OfferingStatus, OfferingType, WALLET_SPOT
from app.services import amm, ledger, offering, token_factory
from tests.test_trading import make_user


def _window():
    now = datetime.now(timezone.utc)
    return now, now - timedelta(minutes=1), now + timedelta(hours=1)


async def _fund_usdt(db, user, usdt, amount):
    await ledger.credit(db, user_id=user.id, asset_id=usdt.id, amount=Decimal(amount),
                        kind=ledger.TransactionKind.DEPOSIT, idempotency_key=f"seed:{user.id}:{amount}")


async def usdt(db) -> Asset:
    a = Asset(symbol="USDT", name="USDT", kind=AssetKind.CRYPTO, scale=8)
    db.add(a)
    await db.flush()
    return a


async def bal(db, user_id, asset_id, wallet=WALLET_SPOT, at=AccountType.AVAILABLE):
    return (await ledger.get_or_create_account(db, asset_id, at, user_id, wallet=wallet)).balance


class TestLaunch:
    async def test_mint_supply_to_creator(self, db):
        u = await make_user(db, "launcher@example.com")
        token = await token_factory.launch(
            db, creator_id=u.id, symbol="MOON", name="Moon Coin", total_supply=Decimal("1000000"),
            purpose="community rewards", target_audience="gamers", offering_type=OfferingType.ICO,
        )
        asset = await db.get(Asset, token.asset_id)
        assert asset.symbol == "MOON" and asset.custodial is False and asset.scale == 18
        assert await bal(db, u.id, asset.id) == Decimal("1000000")
        assert (await ledger.trial_balance(db))["MOON"] == Decimal(0)

    async def test_duplicate_symbol_rejected(self, db):
        u = await make_user(db, "dup@example.com")
        await usdt(db)  # USDT already listed
        with pytest.raises(token_factory.LaunchError, match="already listed"):
            await token_factory.launch(db, creator_id=u.id, symbol="USDT", name="x",
                                       total_supply=Decimal("100"), offering_type=OfferingType.ICO)

    async def test_bad_symbol_and_supply(self, db):
        u = await make_user(db, "bad@example.com")
        with pytest.raises(token_factory.LaunchError, match="symbol"):
            await token_factory.launch(db, creator_id=u.id, symbol="a b", name="x",
                                       total_supply=Decimal("100"), offering_type=OfferingType.ICO)
        with pytest.raises(token_factory.LaunchError, match="supply"):
            await token_factory.launch(db, creator_id=u.id, symbol="ZERO", name="x",
                                       total_supply=Decimal("0"), offering_type=OfferingType.ICO)


class TestOffering:
    async def _launch_and_offer(self, db, creator, soft_cap):
        u_asset = await usdt(db)
        token = await token_factory.launch(db, creator_id=creator.id, symbol="MOON", name="Moon",
                                           total_supply=Decimal("1000000"), offering_type=OfferingType.ICO)
        now, start, end = _window()
        off = await offering.create_offering(
            db, token=token, creator_id=creator.id, sale_price=Decimal("0.5"),
            tokens_for_sale=Decimal("100000"), soft_cap=Decimal(soft_cap), start_at=start, end_at=end,
        )
        return token, off, u_asset, now

    async def test_ico_success_releases_tokens_and_proceeds(self, db):
        creator = await make_user(db, "cr-ok@example.com")
        buyer = await make_user(db, "buy-ok@example.com")
        token, off, u_asset, now = await self._launch_and_offer(db, creator, soft_cap="10000")
        await _fund_usdt(db, buyer, u_asset, "30000")

        await offering.buy(db, offering=off, user_id=buyer.id, usdt_amount=Decimal("25000"), now=now)
        assert off.raised == Decimal("25000") and off.tokens_sold == Decimal("50000")

        assert await offering.close_offering(db, offering=off) is OfferingStatus.SUCCESS
        # Buyer got 50,000 MOON; creator got 25,000 USDT; 50,000 unsold MOON returned (950,000 total).
        assert await bal(db, buyer.id, token.asset_id) == Decimal("50000")
        assert await bal(db, creator.id, u_asset.id) == Decimal("25000")
        assert await bal(db, creator.id, token.asset_id) == Decimal("950000")
        assert (await ledger.trial_balance(db))["MOON"] == Decimal(0)
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_ico_failure_refunds_everyone(self, db):
        creator = await make_user(db, "cr-fail@example.com")
        buyer = await make_user(db, "buy-fail@example.com")
        token, off, u_asset, now = await self._launch_and_offer(db, creator, soft_cap="40000")
        await _fund_usdt(db, buyer, u_asset, "30000")

        await offering.buy(db, offering=off, user_id=buyer.id, usdt_amount=Decimal("25000"), now=now)
        assert await offering.close_offering(db, offering=off) is OfferingStatus.FAILED
        # Refunded: buyer whole again, no tokens; creator's full supply back.
        assert await bal(db, buyer.id, u_asset.id) == Decimal("30000")
        assert await bal(db, buyer.id, token.asset_id) == Decimal("0")
        assert await bal(db, creator.id, token.asset_id) == Decimal("1000000")
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_hard_cap_clamps_and_closes(self, db):
        creator = await make_user(db, "cr-cap@example.com")
        whale = await make_user(db, "whale@example.com")
        token, off, u_asset, now = await self._launch_and_offer(db, creator, soft_cap="10000")
        await _fund_usdt(db, whale, u_asset, "90000")
        # Hard cap = 0.5 * 100,000 = 50,000. A 60,000 buy is clamped to 50,000 for all 100,000 tokens.
        await offering.buy(db, offering=off, user_id=whale.id, usdt_amount=Decimal("60000"), now=now)
        assert off.raised == Decimal("50000") and off.tokens_sold == Decimal("100000")
        with pytest.raises(offering.OfferingError, match="not open"):
            await offering.buy(db, offering=off, user_id=whale.id, usdt_amount=Decimal("1"), now=now)


class TestSTO:
    async def _sto_offer(self, db, creator, *, lockup_days=0):
        u_asset = await usdt(db)
        token = await token_factory.launch(db, creator_id=creator.id, symbol="SECT", name="Security",
                                           total_supply=Decimal("1000000"), offering_type=OfferingType.STO)
        now, start, end = _window()
        lockup = now + timedelta(days=lockup_days) if lockup_days else None
        off = await offering.create_offering(
            db, token=token, creator_id=creator.id, sale_price=Decimal("1"),
            tokens_for_sale=Decimal("100000"), soft_cap=Decimal("0"), start_at=start, end_at=end,
            requires_whitelist=True, lockup_until=lockup,
        )
        return token, off, u_asset, now

    async def test_whitelist_gates_buy(self, db):
        creator = await make_user(db, "sto-cr@example.com")
        outsider = await make_user(db, "outsider@example.com")
        token, off, u_asset, now = await self._sto_offer(db, creator)
        await _fund_usdt(db, outsider, u_asset, "5000")

        with pytest.raises(offering.OfferingError, match="whitelist"):
            await offering.buy(db, offering=off, user_id=outsider.id, usdt_amount=Decimal("1000"), now=now)

        await offering.add_to_whitelist(db, offering=off, creator_id=creator.id, user_id=outsider.id)
        p = await offering.buy(db, offering=off, user_id=outsider.id, usdt_amount=Decimal("1000"), now=now)
        assert p.tokens_bought == Decimal("1000")

    async def test_lockup_blocks_trade_until_expiry(self, db):
        creator = await make_user(db, "sto-lock@example.com")
        inv = await make_user(db, "inv@example.com")
        token, off, u_asset, now = await self._sto_offer(db, creator, lockup_days=30)
        await offering.add_to_whitelist(db, offering=off, creator_id=creator.id, user_id=inv.id)

        # Under lockup → blocked; whitelisted but before expiry.
        with pytest.raises(offering.OfferingError, match="locked"):
            await offering.assert_tradeable(db, token_asset_id=token.asset_id, user_id=inv.id, now=now)
        # After lockup → allowed (whitelisted).
        later = now + timedelta(days=31)
        await offering.assert_tradeable(db, token_asset_id=token.asset_id, user_id=inv.id, now=later)
        # Non-whitelisted still blocked after lockup.
        with pytest.raises(offering.OfferingError, match="whitelisted"):
            await offering.assert_tradeable(db, token_asset_id=token.asset_id, user_id=creator.id + 999, now=later)


class TestPool:
    async def _launch_with_usdt(self, db, creator, usdt_amt):
        u_asset = await usdt(db)
        token = await token_factory.launch(db, creator_id=creator.id, symbol="MOON", name="Moon",
                                           total_supply=Decimal("1000000"), offering_type=OfferingType.ICO)
        await _fund_usdt(db, creator, u_asset, usdt_amt)
        return token, u_asset

    async def test_create_pool_and_seed_liquidity(self, db):
        creator = await make_user(db, "lp-seed@example.com")
        token, u_asset = await self._launch_with_usdt(db, creator, "50000")
        pool = await amm.create_pool(db, token_asset_id=token.asset_id)

        shares = await amm.add_liquidity(db, user_id=creator.id, pool=pool,
                                         token_amt=Decimal("100000"), quote_amt=Decimal("50000"))
        assert pool.reserve_token == Decimal("100000") and pool.reserve_quote == Decimal("50000")
        assert pool.price() == Decimal("0.5")               # 50,000 USDT / 100,000 MOON
        assert pool.lp_supply == shares and shares > 0
        assert await amm.verify_reserves(db, pool) is True
        # Creator spent 100k MOON + 50k USDT.
        assert await bal(db, creator.id, token.asset_id) == Decimal("900000")
        assert await bal(db, creator.id, u_asset.id) == Decimal("0")
        assert (await ledger.trial_balance(db))["MOON"] == Decimal(0)
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_second_add_is_proportional_and_keeps_price(self, db):
        creator = await make_user(db, "lp-add@example.com")
        token, u_asset = await self._launch_with_usdt(db, creator, "55000")
        pool = await amm.create_pool(db, token_asset_id=token.asset_id)
        s1 = await amm.add_liquidity(db, user_id=creator.id, pool=pool,
                                     token_amt=Decimal("100000"), quote_amt=Decimal("50000"))
        # Add 10% more token; USDT is derived from the pool ratio (5,000). Price unchanged.
        s2 = await amm.add_liquidity(db, user_id=creator.id, pool=pool,
                                     token_amt=Decimal("10000"), quote_amt=Decimal("0"))
        assert pool.reserve_token == Decimal("110000") and pool.reserve_quote == Decimal("55000")
        assert pool.price() == Decimal("0.5")
        assert abs(s2 - s1 / Decimal("10")) < Decimal("1e-15")   # 10% of supply → 10% of shares (18dp)
        assert await amm.verify_reserves(db, pool) is True
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)


class TestSwap:
    async def _seeded_pool(self, db, creator, *, token_amt="100000", quote_amt="50000", extra_usdt="0"):
        u_asset = await usdt(db)
        token = await token_factory.launch(db, creator_id=creator.id, symbol="MOON", name="Moon",
                                           total_supply=Decimal("1000000"), offering_type=OfferingType.ICO)
        await _fund_usdt(db, creator, u_asset, str(Decimal(quote_amt) + Decimal(extra_usdt)))
        pool = await amm.create_pool(db, token_asset_id=token.asset_id)
        await amm.add_liquidity(db, user_id=creator.id, pool=pool,
                                token_amt=Decimal(token_amt), quote_amt=Decimal(quote_amt))
        return token, u_asset, pool

    async def test_buy_moves_price_up_and_grows_k(self, db):
        creator = await make_user(db, "sw-cr@example.com")
        buyer = await make_user(db, "sw-buy@example.com")
        token, u_asset, pool = await self._seeded_pool(db, creator)
        await _fund_usdt(db, buyer, u_asset, "10000")
        k0 = pool.reserve_token * pool.reserve_quote

        out = await amm.swap(db, user_id=buyer.id, pool=pool, side="BUY",
                             amount_in=Decimal("10000"), min_out=Decimal("0"), now=datetime.now(timezone.utc))
        assert out > 0
        assert await bal(db, buyer.id, token.asset_id) == out
        assert await bal(db, buyer.id, u_asset.id) == Decimal("0")
        assert pool.reserve_quote == Decimal("60000") and pool.reserve_token == Decimal("100000") - out
        assert pool.reserve_token * pool.reserve_quote >= k0        # fee grows k
        assert pool.price() > Decimal("0.5")                        # price rose
        assert await amm.verify_reserves(db, pool) is True
        assert (await ledger.trial_balance(db))["MOON"] == Decimal(0)
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_sell_and_slippage_guard(self, db):
        creator = await make_user(db, "sw-sell@example.com")
        token, u_asset, pool = await self._seeded_pool(db, creator)
        # Creator still holds 900,000 MOON; sell 10,000 for USDT.
        out = await amm.swap(db, user_id=creator.id, pool=pool, side="SELL",
                             amount_in=Decimal("10000"), min_out=Decimal("0"), now=datetime.now(timezone.utc))
        assert out > 0 and pool.reserve_token == Decimal("110000")
        # Slippage: demand an impossibly high min_out → rejected, nothing moves.
        with pytest.raises(amm.AmmError, match="slippage"):
            await amm.swap(db, user_id=creator.id, pool=pool, side="SELL",
                           amount_in=Decimal("10000"), min_out=Decimal("999999"), now=datetime.now(timezone.utc))
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)

    async def test_valuation_fdv(self, db):
        creator = await make_user(db, "sw-val@example.com")
        token, u_asset, pool = await self._seeded_pool(db, creator)
        assert pool.price() == Decimal("0.5")
        assert amm.fdv(pool, Decimal("1000000")) == Decimal("500000")   # 0.5 × 1,000,000

    async def test_sto_swap_blocked_by_lockup(self, db):
        creator = await make_user(db, "sto-sw@example.com")
        outsider = await make_user(db, "sto-out@example.com")
        u_asset = await usdt(db)
        token = await token_factory.launch(db, creator_id=creator.id, symbol="SECT", name="Sec",
                                           total_supply=Decimal("1000000"), offering_type=OfferingType.STO)
        now, start, end = _window()
        await offering.create_offering(
            db, token=token, creator_id=creator.id, sale_price=Decimal("1"),
            tokens_for_sale=Decimal("100000"), soft_cap=Decimal("0"), start_at=start, end_at=end,
            requires_whitelist=True, lockup_until=now + timedelta(days=30),
        )
        await _fund_usdt(db, creator, u_asset, "50000")
        await _fund_usdt(db, outsider, u_asset, "5000")
        pool = await amm.create_pool(db, token_asset_id=token.asset_id)
        await amm.add_liquidity(db, user_id=creator.id, pool=pool,
                                token_amt=Decimal("100000"), quote_amt=Decimal("50000"))
        with pytest.raises(offering.OfferingError, match="locked"):
            await amm.swap(db, user_id=outsider.id, pool=pool, side="BUY",
                           amount_in=Decimal("1000"), min_out=Decimal("0"), now=now)


class TestRemoveLiquidity:
    async def test_remove_returns_proportional_reserves(self, db):
        creator = await make_user(db, "rm@example.com")
        u_asset = await usdt(db)
        token = await token_factory.launch(db, creator_id=creator.id, symbol="MOON", name="Moon",
                                           total_supply=Decimal("1000000"), offering_type=OfferingType.ICO)
        await _fund_usdt(db, creator, u_asset, "50000")
        pool = await amm.create_pool(db, token_asset_id=token.asset_id)
        shares = await amm.add_liquidity(db, user_id=creator.id, pool=pool,
                                         token_amt=Decimal("100000"), quote_amt=Decimal("50000"))

        # Remove half → get back half the reserves.
        tok, quo = await amm.remove_liquidity(db, user_id=creator.id, pool=pool, shares=shares / 2)
        assert tok == Decimal("50000") and quo == Decimal("25000")
        assert pool.reserve_token == Decimal("50000") and pool.reserve_quote == Decimal("25000")
        assert await amm.verify_reserves(db, pool) is True

        # Remove the rest → pool drained, provider whole (minus rounding dust).
        await amm.remove_liquidity(db, user_id=creator.id, pool=pool, shares=shares / 2)
        assert pool.lp_supply == Decimal(0)
        assert abs(await bal(db, creator.id, token.asset_id) - Decimal("1000000")) < Decimal("1e-12")
        assert abs(await bal(db, creator.id, u_asset.id) - Decimal("50000")) < Decimal("1e-12")
        assert (await ledger.trial_balance(db))["MOON"] == Decimal(0)
        assert (await ledger.trial_balance(db))["USDT"] == Decimal(0)
