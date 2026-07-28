"""Margin service: accounts, collateral, borrowing, hourly interest, repayment.

The money rules, all enforced here:

- **Collateral is the user's own funds**, moved spot -> margin. Borrowed funds are the exchange's,
  tracked as a loan and mirrored by the negative MARGIN_BORROWED pool.
- **Leverage bounds borrowing.** With collateral equity E (USD) and gross margin assets G, a borrow
  is allowed only while G stays within E x leverage. So max additional borrow = E x leverage - G.
- **Interest accrues hourly** at a flat rate on the outstanding principal, and is realised as fee
  income when the loan is repaid.

Valuation is injected as `price_of(symbol) -> USD`, so this module never reaches for the network and
tests stay deterministic. Health/liquidation build on `account_state` in a later stage.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Account,
    AccountType,
    Asset,
    Market,
    MarginAccount,
    MarginAccountStatus,
    MarginLoan,
    MarginLoanStatus,
    MarginMode,
    MarginTier,
    OrderSide,
    OrderType,
    WALLET_SPOT,
)
from app.services import ledger, trading
from app.services.ledger import InsufficientFunds, LedgerError

PriceOf = Callable[[str], Awaitable[Decimal | None]]

# Leverage ceilings. Cross depends on tier; isolated is capped per the pair (10x max here).
CROSS_CAP = {MarginTier.CLASSIC: Decimal("3"), MarginTier.PRO: Decimal("20")}
ISOLATED_CAP = Decimal("10")

# Flat hourly interest on borrowed principal. ~0.0125%/hour ≈ 0.3%/day — in Binance's ballpark.
DEFAULT_HOURLY_RATE = Decimal("0.000125")


class MarginError(Exception):
    """A margin action was refused. Safe to surface to a caller."""


def leverage_cap(mode: MarginMode, tier: MarginTier) -> Decimal:
    return ISOLATED_CAP if mode is MarginMode.ISOLATED else CROSS_CAP[tier]


async def open_account(
    db: AsyncSession,
    *,
    user_id: int,
    mode: MarginMode = MarginMode.CROSS,
    symbol: str | None = None,
    tier: MarginTier = MarginTier.CLASSIC,
    leverage: Decimal | None = None,
) -> MarginAccount:
    """Open a margin account. Defaults to cross; isolated needs a symbol. Leverage is validated
    against the mode/tier ceiling and defaults to it."""
    if mode is MarginMode.ISOLATED and not symbol:
        raise MarginError("isolated margin needs a symbol")
    if mode is MarginMode.CROSS and symbol:
        raise MarginError("cross margin spans all pairs; no symbol")
    symbol = symbol.upper() if symbol else None

    cap = leverage_cap(mode, tier)
    lev = leverage if leverage is not None else cap
    if lev < 1 or lev > cap:
        raise MarginError(f"leverage must be between 1x and {cap}x for this account")

    existing = await get_account(db, user_id=user_id, mode=mode, symbol=symbol)
    if existing is not None:
        raise MarginError("margin account already exists")

    account = MarginAccount(
        user_id=user_id, mode=mode, symbol=symbol, tier=tier, max_leverage=lev,
        status=MarginAccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()
    return account


async def get_account(
    db: AsyncSession, *, user_id: int, mode: MarginMode, symbol: str | None
) -> MarginAccount | None:
    q = select(MarginAccount).where(MarginAccount.user_id == user_id, MarginAccount.mode == mode)
    q = q.where(MarginAccount.symbol == symbol.upper()) if symbol else q.where(MarginAccount.symbol.is_(None))
    return (await db.execute(q)).scalar_one_or_none()


async def set_leverage(db: AsyncSession, *, account: MarginAccount, leverage: Decimal) -> MarginAccount:
    cap = leverage_cap(account.mode, account.tier)
    if leverage < 1 or leverage > cap:
        raise MarginError(f"leverage must be between 1x and {cap}x")
    account.max_leverage = leverage
    return account


async def transfer_collateral(
    db: AsyncSession, *, account: MarginAccount, asset_id: int, amount: Decimal, deposit: bool
) -> None:
    """Move collateral between the user's spot wallet and this margin account (deposit or withdraw)."""
    if amount <= 0:
        raise MarginError("amount must be positive")
    src, dst = (WALLET_SPOT, account.wallet) if deposit else (account.wallet, WALLET_SPOT)
    try:
        await ledger.transfer_wallet(
            db, user_id=account.user_id, asset_id=asset_id, amount=amount,
            from_wallet=src, to_wallet=dst,
            idempotency_key=f"margin-xfer:{account.id}:{asset_id}:{'in' if deposit else 'out'}:{amount}",
            reference=f"margin-account={account.id}",
        )
    except InsufficientFunds as exc:
        raise MarginError(str(exc)) from exc


# --- valuation & state ----------------------------------------------------------------------------

@dataclass(frozen=True)
class AccountState:
    gross_usd: Decimal      # all margin-wallet assets valued in USD
    debt_usd: Decimal       # outstanding loans (principal + accrued interest) in USD
    equity_usd: Decimal     # the user's own money: gross - debt
    max_borrow_usd: Decimal  # additional borrow the leverage still allows
    margin_level: Decimal | None  # gross / debt; None when there is no debt


async def _wallet_balances(db: AsyncSession, *, user_id: int, wallet: str) -> dict[str, Decimal]:
    """Symbol -> total (AVAILABLE + LOCKED) balance in a user's sub-wallet."""
    rows = (
        await db.execute(
            select(Asset.symbol, Account.balance)
            .join(Account, Account.asset_id == Asset.id)
            .where(
                Account.user_id == user_id,
                Account.wallet == wallet,
                Account.account_type.in_([AccountType.AVAILABLE, AccountType.LOCKED]),
            )
        )
    ).all()
    out: dict[str, Decimal] = {}
    for symbol, balance in rows:
        out[symbol] = out.get(symbol, Decimal(0)) + balance
    return out


async def open_loans(db: AsyncSession, account: MarginAccount) -> list[MarginLoan]:
    return list(
        (
            await db.execute(
                select(MarginLoan).where(
                    MarginLoan.margin_account_id == account.id,
                    MarginLoan.status == MarginLoanStatus.OPEN,
                )
            )
        ).scalars().all()
    )


async def account_state(db: AsyncSession, account: MarginAccount, price_of: PriceOf) -> AccountState:
    balances = await _wallet_balances(db, user_id=account.user_id, wallet=account.wallet)
    gross = Decimal(0)
    for symbol, amount in balances.items():
        px = await price_of(symbol)
        if px is not None:
            gross += amount * px

    debt = Decimal(0)
    loans = await open_loans(db, account)
    symbols = {a.id: a.symbol for a in (await db.execute(select(Asset))).scalars().all()}
    for loan in loans:
        px = await price_of(symbols.get(loan.asset_id, ""))
        if px is not None:
            debt += loan.owed * px

    equity = gross - debt
    # Leverage rule: gross may grow to equity x leverage; the slack is what can still be borrowed.
    max_borrow = equity * account.max_leverage - gross
    if max_borrow < 0:
        max_borrow = Decimal(0)
    margin_level = (gross / debt) if debt > 0 else None
    return AccountState(gross_usd=gross, debt_usd=debt, equity_usd=equity,
                        max_borrow_usd=max_borrow, margin_level=margin_level)


# --- borrow / accrue / repay ----------------------------------------------------------------------

async def borrow(
    db: AsyncSession,
    *,
    account: MarginAccount,
    asset_id: int,
    amount: Decimal,
    price_of: PriceOf,
    hourly_rate: Decimal = DEFAULT_HOURLY_RATE,
    now: datetime,
) -> MarginLoan:
    """Borrow `amount` of an asset into this margin account, within the leverage limit."""
    if amount <= 0:
        raise MarginError("borrow amount must be positive")
    if account.status is not MarginAccountStatus.ACTIVE:
        raise MarginError("margin account is not active")

    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise MarginError("unknown asset")
    px = await price_of(asset.symbol)
    if px is None:
        raise MarginError(f"no price for {asset.symbol}")

    state = await account_state(db, account, price_of)
    want_usd = amount * px
    if want_usd > state.max_borrow_usd:
        raise MarginError(
            f"borrow exceeds {account.max_leverage}x limit "
            f"(want ${want_usd:.2f}, available ${state.max_borrow_usd:.2f})"
        )

    try:
        await ledger.margin_borrow(
            db, user_id=account.user_id, asset_id=asset_id, amount=amount, wallet=account.wallet,
            idempotency_key=f"margin-borrow:{account.id}:{asset_id}:{now.isoformat()}",
            reference=f"margin-account={account.id}",
        )
    except LedgerError as exc:
        raise MarginError(str(exc)) from exc

    # Fold into an existing open loan for the asset, or open a new one. One open loan per asset keeps
    # accrual simple.
    loan = (
        await db.execute(
            select(MarginLoan).where(
                MarginLoan.margin_account_id == account.id,
                MarginLoan.asset_id == asset_id,
                MarginLoan.status == MarginLoanStatus.OPEN,
            )
        )
    ).scalar_one_or_none()
    if loan is None:
        loan = MarginLoan(
            margin_account_id=account.id, asset_id=asset_id, principal=amount,
            accrued_interest=Decimal(0), hourly_rate=hourly_rate, status=MarginLoanStatus.OPEN,
            last_accrued_at=now,
        )
        db.add(loan)
        await db.flush()
    else:
        loan.principal += amount
    return loan


def _accrue(loan: MarginLoan, now: datetime) -> Decimal:
    """Advance a single loan's accrued interest by whole elapsed hours. Returns interest added."""
    elapsed = now - loan.last_accrued_at
    hours = int(elapsed.total_seconds() // 3600)
    if hours <= 0:
        return Decimal(0)
    added = loan.principal * loan.hourly_rate * hours
    loan.accrued_interest += added
    loan.last_accrued_at = loan.last_accrued_at + timedelta(hours=hours)
    return added


async def accrue_interest(db: AsyncSession, *, now: datetime) -> Decimal:
    """Accrue interest on every open loan for the whole hours elapsed. Returns total added."""
    loans = (
        await db.execute(select(MarginLoan).where(MarginLoan.status == MarginLoanStatus.OPEN))
    ).scalars().all()
    total = Decimal(0)
    for loan in loans:
        total += _accrue(loan, now)
    return total


async def repay(
    db: AsyncSession, *, account: MarginAccount, loan: MarginLoan, amount: Decimal
) -> MarginLoan:
    """Repay a loan. Interest is cleared first, then principal. Closes the loan when nothing is owed."""
    if amount <= 0:
        raise MarginError("repay amount must be positive")
    if loan.status is not MarginLoanStatus.OPEN:
        raise MarginError("loan is not open")

    pay = min(amount, loan.owed)
    interest_part = min(pay, loan.accrued_interest)
    principal_part = pay - interest_part

    try:
        await ledger.margin_repay(
            db, user_id=account.user_id, asset_id=loan.asset_id,
            principal=principal_part, interest=interest_part, wallet=account.wallet,
            idempotency_key=f"margin-repay:{loan.id}:{loan.principal}:{loan.accrued_interest}",
            reference=f"margin-loan={loan.id}",
        )
    except InsufficientFunds as exc:
        raise MarginError(str(exc)) from exc

    loan.accrued_interest -= interest_part
    loan.principal -= principal_part
    if loan.owed == 0:
        loan.status = MarginLoanStatus.REPAID
    return loan


# --- margin trading -------------------------------------------------------------------------------

async def _price_in_quote(base_symbol: str, quote_symbol: str, price_of: PriceOf) -> Decimal | None:
    """Convert a base asset's USD price into units of the quote asset (usually ~1 for USDT)."""
    base_usd = await price_of(base_symbol)
    quote_usd = await price_of(quote_symbol)
    if base_usd is None or quote_usd is None or quote_usd == 0:
        return None
    return base_usd / quote_usd


async def place_margin_order(
    db: AsyncSession,
    *,
    account: MarginAccount,
    market: Market,
    side: OrderSide,
    order_type: OrderType,
    quantity: Decimal,
    price: Decimal | None,
    price_of: PriceOf,
    now: datetime,
    auto_borrow: bool = True,
) -> trading.PlacedOrder:
    """Place an order that trades from this margin account's wallet.

    With `auto_borrow`, any shortfall in the funds the order needs is borrowed first (within the
    leverage limit): a buy borrows quote, a sell borrows base — so a sell you can't cover becomes a
    short. The order then locks and settles entirely in the margin wallet, never touching spot.
    """
    if account.status is not MarginAccountStatus.ACTIVE:
        raise MarginError("margin account is not active")
    if account.mode is MarginMode.ISOLATED and account.symbol != market.symbol:
        raise MarginError("this isolated account does not trade that pair")

    base = await db.get(Asset, market.base_asset_id)
    quote = await db.get(Asset, market.quote_asset_id)

    # What the order will need locked, and in which asset.
    if side is OrderSide.BUY:
        need_asset_id, need_symbol = market.quote_asset_id, quote.symbol
        px = price if (order_type is OrderType.LIMIT and price) else await _price_in_quote(base.symbol, quote.symbol, price_of)
        if px is None:
            raise MarginError("no price to size the borrow")
        required = px * quantity
    else:
        need_asset_id, need_symbol = market.base_asset_id, base.symbol
        required = quantity

    if auto_borrow:
        avail = (await ledger.get_or_create_account(
            db, need_asset_id, AccountType.AVAILABLE, account.user_id, wallet=account.wallet
        )).balance
        if avail < required:
            await borrow(db, account=account, asset_id=need_asset_id, amount=required - avail,
                         price_of=price_of, now=now)

    try:
        return await trading.place_order(
            db, user_id=account.user_id, market=market, side=side, order_type=order_type,
            quantity=quantity, price=price, wallet=account.wallet,
        )
    except trading.TradingError as exc:
        raise MarginError(str(exc)) from exc


# --- health & liquidation -------------------------------------------------------------------------

# Margin level (gross assets / debt) thresholds, mirroring Binance's cross-margin bands.
MARGIN_CALL_LEVEL = Decimal("1.3")   # warn the user to add margin or reduce
LIQUIDATION_LEVEL = Decimal("1.1")   # force-close at or below this
LIQUIDATION_FEE_RATE = Decimal("0.02")  # 2% of debt repaid, to the insurance fund


def health_status(margin_level: Decimal | None) -> str:
    if margin_level is None:
        return "safe"  # no debt
    if margin_level <= LIQUIDATION_LEVEL:
        return "liquidatable"
    if margin_level <= MARGIN_CALL_LEVEL:
        return "margin_call"
    return "safe"


async def _margin_available(db: AsyncSession, account: MarginAccount, asset_id: int) -> Decimal:
    return (await ledger.get_or_create_account(
        db, asset_id, AccountType.AVAILABLE, account.user_id, wallet=account.wallet
    )).balance


async def liquidate(
    db: AsyncSession,
    *,
    account: MarginAccount,
    market: Market,
    price_of: PriceOf,
    now: datetime,
    fee_rate: Decimal = LIQUIDATION_FEE_RATE,
) -> bool:
    """Force-close an underwater account on `market` and repay its loans. No-op if it is healthy.

    Interest is accrued first so the check sees the true debt. The position is flattened with a
    margin market order — a long sells its base, a short buys the base back — and the freed funds
    repay the loans. A liquidation fee on the repaid debt goes to the insurance fund (FEE_INCOME).
    Returns True if it liquidated.
    """
    await accrue_interest(db, now=now)
    state = await account_state(db, account, price_of)
    if health_status(state.margin_level) != "liquidatable":
        return False

    loans = await open_loans(db, account)
    quote_loan = next((ln for ln in loans if ln.asset_id == market.quote_asset_id), None)
    base_loan = next((ln for ln in loans if ln.asset_id == market.base_asset_id), None)

    if quote_loan is not None:
        # Long: owes quote, holds base. Sell all the base held to raise quote.
        base_held = await _margin_available(db, account, market.base_asset_id)
        if base_held > 0:
            await place_margin_order(
                db, account=account, market=market, side=OrderSide.SELL, order_type=OrderType.MARKET,
                quantity=_floor(base_held, market.qty_step), price=None, price_of=price_of, now=now,
                auto_borrow=False,
            )
    if base_loan is not None:
        # Short: owes base, holds quote. Buy the base back to cover.
        await place_margin_order(
            db, account=account, market=market, side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=_floor(base_loan.owed, market.qty_step), price=None, price_of=price_of, now=now,
            auto_borrow=False,
        )

    # Repay what we can, then skim the liquidation fee off the remaining margin balance.
    repaid_value = Decimal(0)
    for loan in await open_loans(db, account):
        avail = await _margin_available(db, account, loan.asset_id)
        pay = min(avail, loan.owed)
        if pay > 0:
            await repay(db, account=account, loan=loan, amount=pay)
            px = await price_of((await db.get(Asset, loan.asset_id)).symbol) or Decimal(0)
            repaid_value += pay * px

    fee = repaid_value * fee_rate
    if fee > 0:
        px = await price_of((await db.get(Asset, market.quote_asset_id)).symbol) or Decimal(1)
        fee_in_quote = _floor(fee / px, market.qty_step) if px else Decimal(0)
        if fee_in_quote > 0:
            await ledger.collect_fee(
                db, user_id=account.user_id, asset_id=market.quote_asset_id, amount=fee_in_quote,
                wallet=account.wallet, kind=ledger.TransactionKind.FEE,
                idempotency_key=f"liq-fee:{account.id}:{now.isoformat()}",
                reference=f"liquidation margin-account={account.id}",
            )
    return True


def _floor(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


async def liquidatable_accounts(db: AsyncSession, account_price_of) -> list[MarginAccount]:
    """Every active account whose margin level has fallen to the liquidation band."""
    accounts = (
        await db.execute(select(MarginAccount).where(MarginAccount.status == MarginAccountStatus.ACTIVE))
    ).scalars().all()
    out: list[MarginAccount] = []
    for account in accounts:
        state = await account_state(db, account, account_price_of)
        if health_status(state.margin_level) == "liquidatable":
            out.append(account)
    return out
