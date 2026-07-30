"""Referral program: codes, sign-up linking, and fee commission (from FEE_INCOME, trial-balance zero)."""

from decimal import Decimal

from app.models import AccountType, TransactionKind
from app.services import ledger, referral
from tests.test_trading import bal, make_market, make_user


async def price_of(_symbol):  # deterministic USD valuation for earned_usd
    return Decimal("1")


class TestCodesAndLinking:
    async def test_code_is_stable(self, db):
        u = await make_user(db, "ref-code@example.com")
        c1 = await referral.get_or_create_code(db, u)
        c2 = await referral.get_or_create_code(db, u)
        assert c1 == c2 and len(c1) == 8

    async def test_link_signup(self, db):
        referrer = await make_user(db, "ref-parent@example.com")
        code = await referral.get_or_create_code(db, referrer)
        referee = await make_user(db, "ref-child@example.com")
        await referral.link_signup(db, referee=referee, code=code)
        link = await referral.referrer_of(db, referee.id)
        assert link is not None and link.referrer_id == referrer.id

    async def test_bad_or_self_code_ignored(self, db):
        u = await make_user(db, "ref-self@example.com")
        code = await referral.get_or_create_code(db, u)
        await referral.link_signup(db, referee=u, code=code)          # self — ignored
        await referral.link_signup(db, referee=u, code="NOSUCH99")    # unknown — ignored
        assert await referral.referrer_of(db, u.id) is None


class TestCommission:
    async def test_commission_paid_from_fee_income(self, db):
        m = await make_market(db)  # TBASE/TQUOTE
        referrer = await make_user(db, "ref-earn-parent@example.com")
        code = await referral.get_or_create_code(db, referrer)
        referee = await make_user(db, "ref-earn-child@example.com")
        await referral.link_signup(db, referee=referee, code=code)

        # Simulate a fee the referee paid: seed FEE_INCOME with 10 TQUOTE.
        fee_income = await ledger.get_or_create_account(db, m.quote_asset_id, AccountType.FEE_INCOME)
        external = await ledger.get_or_create_account(db, m.quote_asset_id, AccountType.EXTERNAL)
        await ledger.post(db, idempotency_key="seed-fee", kind=TransactionKind.FEE,
                          movements=[ledger.Movement(fee_income, Decimal("10")), ledger.Movement(external, Decimal("-10"))])

        # Referee paid a 10 TQUOTE fee → referrer earns 20% = 2 TQUOTE.
        await referral.pay_commission(db, referee_id=referee.id, asset_id=m.quote_asset_id,
                                      fee_amount=Decimal("10"), usd_price=Decimal("1"))
        assert await bal(db, referrer.id, m.quote_asset_id) == Decimal("2")
        # FEE_INCOME reduced by the payout; trial balance still zero.
        assert (await ledger.get_or_create_account(db, m.quote_asset_id, AccountType.FEE_INCOME)).balance == Decimal("8")
        assert (await ledger.trial_balance(db))["TQUOTE"] == Decimal(0)
        # Tracked on the link for display.
        link = await referral.referrer_of(db, referee.id)
        assert link.earned_usd == Decimal("2")

    async def test_no_commission_when_unreferred(self, db):
        m = await make_market(db)
        lone = await make_user(db, "ref-lone@example.com")
        # No referrer → no-op, no error.
        await referral.pay_commission(db, referee_id=lone.id, asset_id=m.quote_asset_id,
                                      fee_amount=Decimal("10"), usd_price=Decimal("1"))
        assert (await ledger.trial_balance(db)).get("TQUOTE", Decimal(0)) == Decimal(0)
