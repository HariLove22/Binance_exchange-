"""Token offering: a fixed-price primary sale (ICO/STO) with escrow, soft/hard cap, and refunds.

Flow:
  create   -> creator escrows `tokens_for_sale` into the offering (wallet OFFERING:{id} on the house
              account). Status DRAFT.
  buy      -> during the window a buyer pays USDT into escrow and is recorded a SalePurchase. Tokens
              are NOT released yet — they wait for a successful close so a failed raise can refund.
  close    -> raised >= soft_cap  => SUCCESS: release USDT to the creator and tokens to each buyer,
              return unsold tokens to the creator.
              raised <  soft_cap   => FAILED: refund every buyer's USDT, return all tokens.

Escrow is held on the house (market-maker) account under a per-offering wallet, so buyer funds are
never commingled with anyone's tradeable balance and every move is a balanced ledger posting.
STO compliance (whitelist, lockup) is enforced in `_assert_can_buy` / on release.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Asset,
    InvestorWhitelist,
    LaunchedToken,
    OfferingStatus,
    OfferingType,
    SalePurchase,
    TokenOffering,
    WALLET_SPOT,
)
from app.services import ledger, marketmaker
from app.services.ledger import InsufficientFunds, TransactionKind

QUOTE = "USDT"


class OfferingError(Exception):
    """An offering action was refused. Safe to surface to a caller."""


def _escrow_wallet(offering_id: int) -> str:
    return f"OFFERING:{offering_id}"


async def _asset(db: AsyncSession, symbol: str) -> Asset:
    a = (await db.execute(select(Asset).where(Asset.symbol == symbol))).scalar_one_or_none()
    if a is None:
        raise OfferingError(f"{symbol} is not listed")
    return a


async def create_offering(
    db: AsyncSession,
    *,
    token: LaunchedToken,
    creator_id: int,
    sale_price: Decimal,
    tokens_for_sale: Decimal,
    soft_cap: Decimal,
    start_at: datetime,
    end_at: datetime,
    requires_whitelist: bool = False,
    lockup_until: datetime | None = None,
) -> TokenOffering:
    """Open a sale of a launched token: escrow the tokens, set price and caps."""
    if token.creator_id != creator_id:
        raise OfferingError("only the token creator can open an offering")
    if sale_price <= 0 or tokens_for_sale <= 0:
        raise OfferingError("sale price and tokens for sale must be positive")
    if end_at <= start_at:
        raise OfferingError("end must be after start")

    hard_cap = sale_price * tokens_for_sale
    if soft_cap < 0 or soft_cap > hard_cap:
        raise OfferingError("soft cap must be between 0 and the hard cap")

    offering = TokenOffering(
        token_asset_id=token.asset_id, offering_type=token.offering_type, sale_price=sale_price,
        tokens_for_sale=tokens_for_sale, hard_cap=hard_cap, soft_cap=soft_cap, raised=Decimal(0),
        tokens_sold=Decimal(0), start_at=start_at, end_at=end_at, status=OfferingStatus.DRAFT,
        requires_whitelist=requires_whitelist and token.offering_type is OfferingType.STO,
        lockup_until=lockup_until,
    )
    db.add(offering)
    await db.flush()

    # Escrow the tokens from the creator into the offering.
    house = await marketmaker.get_market_maker(db)
    try:
        await ledger.transfer_between(
            db, from_user_id=creator_id, from_wallet=WALLET_SPOT,
            to_user_id=house.id, to_wallet=_escrow_wallet(offering.id),
            asset_id=token.asset_id, amount=tokens_for_sale, kind=TransactionKind.ADJUSTMENT,
            idempotency_key=f"offer-escrow:{offering.id}", reference=f"offering {offering.id} escrow",
        )
    except InsufficientFunds as exc:
        raise OfferingError(str(exc)) from exc
    return offering


def is_open(offering: TokenOffering, now: datetime) -> bool:
    return (
        offering.status in (OfferingStatus.DRAFT, OfferingStatus.LIVE)
        and offering.start_at <= now <= offering.end_at
        and offering.raised < offering.hard_cap
        and offering.tokens_sold < offering.tokens_for_sale
    )


async def _assert_can_buy(db: AsyncSession, offering: TokenOffering, user_id: int) -> None:
    if offering.requires_whitelist:
        row = (await db.execute(
            select(InvestorWhitelist).where(
                InvestorWhitelist.offering_id == offering.id, InvestorWhitelist.user_id == user_id
            )
        )).scalar_one_or_none()
        if row is None:
            raise OfferingError("this security-token offering is restricted to whitelisted investors")


async def buy(
    db: AsyncSession, *, offering: TokenOffering, user_id: int, usdt_amount: Decimal, now: datetime
) -> SalePurchase:
    """Buy into an offering at the fixed price. USDT is escrowed; tokens release on a successful close."""
    if usdt_amount <= 0:
        raise OfferingError("amount must be positive")
    if not is_open(offering, now):
        raise OfferingError("offering is not open")
    await _assert_can_buy(db, offering, user_id)

    # Clamp to what's left, by both the USDT hard cap and the token supply.
    remaining_usdt = offering.hard_cap - offering.raised
    remaining_tokens = offering.tokens_for_sale - offering.tokens_sold
    pay = min(usdt_amount, remaining_usdt)
    tokens = pay / offering.sale_price
    if tokens > remaining_tokens:
        tokens = remaining_tokens
        pay = tokens * offering.sale_price
    if pay <= 0 or tokens <= 0:
        raise OfferingError("offering is fully subscribed")

    house = await marketmaker.get_market_maker(db)
    usdt = await _asset(db, QUOTE)
    purchase = SalePurchase(offering_id=offering.id, user_id=user_id, usdt_paid=pay, tokens_bought=tokens)
    db.add(purchase)
    await db.flush()

    try:
        await ledger.transfer_between(
            db, from_user_id=user_id, from_wallet=WALLET_SPOT,
            to_user_id=house.id, to_wallet=_escrow_wallet(offering.id),
            asset_id=usdt.id, amount=pay, kind=TransactionKind.ADJUSTMENT,
            idempotency_key=f"offer-buy:{purchase.id}", reference=f"offering {offering.id} buy",
        )
    except InsufficientFunds as exc:
        raise OfferingError(str(exc)) from exc

    offering.raised += pay
    offering.tokens_sold += tokens
    offering.status = OfferingStatus.LIVE
    return purchase


# --- STO compliance -------------------------------------------------------------------------------

async def add_to_whitelist(db: AsyncSession, *, offering: TokenOffering, creator_id: int, user_id: int) -> None:
    """Approve an investor to buy/hold a security token. Creator-only."""
    token = (await db.execute(
        select(LaunchedToken).where(LaunchedToken.asset_id == offering.token_asset_id)
    )).scalar_one()
    if token.creator_id != creator_id:
        raise OfferingError("only the token creator can manage the whitelist")
    if offering.offering_type is not OfferingType.STO:
        raise OfferingError("whitelist only applies to STO offerings")
    exists = (await db.execute(
        select(InvestorWhitelist).where(
            InvestorWhitelist.offering_id == offering.id, InvestorWhitelist.user_id == user_id
        )
    )).scalar_one_or_none()
    if exists is None:
        db.add(InvestorWhitelist(offering_id=offering.id, user_id=user_id))
        await db.flush()


async def assert_tradeable(db: AsyncSession, *, token_asset_id: int, user_id: int, now: datetime) -> None:
    """Guard a token trade for STO rules: enforce lockup and whitelist. No-op for ICO / plain assets.

    Called by the AMM swap and liquidity paths so a security token can't move before its lockup or
    into a non-whitelisted holder.
    """
    off = (await db.execute(
        select(TokenOffering).where(TokenOffering.token_asset_id == token_asset_id)
        .order_by(TokenOffering.id.desc())
    )).scalars().first()
    if off is None or off.offering_type is not OfferingType.STO:
        return
    if off.lockup_until is not None and now < off.lockup_until:
        raise OfferingError(f"token is locked until {off.lockup_until.isoformat()}")
    if off.requires_whitelist:
        wl = (await db.execute(
            select(InvestorWhitelist).where(
                InvestorWhitelist.offering_id == off.id, InvestorWhitelist.user_id == user_id
            )
        )).scalar_one_or_none()
        if wl is None:
            raise OfferingError("security token can only be traded by whitelisted investors")


async def _purchases(db: AsyncSession, offering_id: int) -> list[SalePurchase]:
    return list((await db.execute(
        select(SalePurchase).where(SalePurchase.offering_id == offering_id)
    )).scalars().all())


async def close_offering(db: AsyncSession, *, offering: TokenOffering) -> OfferingStatus:
    """Settle an offering: SUCCESS releases funds/tokens, FAILED refunds everyone. Idempotent-ish."""
    if offering.status in (OfferingStatus.SUCCESS, OfferingStatus.FAILED):
        return offering.status

    house = await marketmaker.get_market_maker(db)
    escrow = _escrow_wallet(offering.id)
    usdt = await _asset(db, QUOTE)
    token_asset_id = offering.token_asset_id
    purchases = await _purchases(db, offering.id)

    if offering.raised >= offering.soft_cap:
        # SUCCESS: creator gets the raised USDT; buyers get their tokens; unsold tokens go back.
        token = (await db.execute(
            select(LaunchedToken).where(LaunchedToken.asset_id == token_asset_id)
        )).scalar_one()
        if offering.raised > 0:
            await ledger.transfer_between(
                db, from_user_id=house.id, from_wallet=escrow, to_user_id=token.creator_id,
                to_wallet=WALLET_SPOT, asset_id=usdt.id, amount=offering.raised,
                kind=TransactionKind.ADJUSTMENT, idempotency_key=f"offer-release-usdt:{offering.id}",
                reference=f"offering {offering.id} proceeds",
            )
        for p in purchases:
            await ledger.transfer_between(
                db, from_user_id=house.id, from_wallet=escrow, to_user_id=p.user_id,
                to_wallet=WALLET_SPOT, asset_id=token_asset_id, amount=p.tokens_bought,
                kind=TransactionKind.ADJUSTMENT, idempotency_key=f"offer-release-tok:{p.id}",
                reference=f"offering {offering.id} allocation",
            )
        leftover = offering.tokens_for_sale - offering.tokens_sold
        if leftover > 0:
            await ledger.transfer_between(
                db, from_user_id=house.id, from_wallet=escrow, to_user_id=token.creator_id,
                to_wallet=WALLET_SPOT, asset_id=token_asset_id, amount=leftover,
                kind=TransactionKind.ADJUSTMENT, idempotency_key=f"offer-leftover:{offering.id}",
                reference=f"offering {offering.id} unsold",
            )
        offering.status = OfferingStatus.SUCCESS
    else:
        # FAILED: refund every buyer, return all tokens to the creator.
        token = (await db.execute(
            select(LaunchedToken).where(LaunchedToken.asset_id == token_asset_id)
        )).scalar_one()
        for p in purchases:
            if p.refunded:
                continue
            await ledger.transfer_between(
                db, from_user_id=house.id, from_wallet=escrow, to_user_id=p.user_id,
                to_wallet=WALLET_SPOT, asset_id=usdt.id, amount=p.usdt_paid,
                kind=TransactionKind.ADJUSTMENT, idempotency_key=f"offer-refund:{p.id}",
                reference=f"offering {offering.id} refund",
            )
            p.refunded = True
        await ledger.transfer_between(
            db, from_user_id=house.id, from_wallet=escrow, to_user_id=token.creator_id,
            to_wallet=WALLET_SPOT, asset_id=token_asset_id, amount=offering.tokens_for_sale,
            kind=TransactionKind.ADJUSTMENT, idempotency_key=f"offer-return:{offering.id}",
            reference=f"offering {offering.id} tokens returned",
        )
        offering.status = OfferingStatus.FAILED
    return offering.status
