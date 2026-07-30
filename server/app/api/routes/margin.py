"""Margin endpoints: open an account, move collateral, borrow/repay, trade, and read health.

Every money action commits inside one request/transaction. Valuation for leverage and health uses
the live Binance reference price (stablecoins = $1), injected into the service so the service itself
never reaches for the network.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import (
    Asset,
    Market,
    MarginAccount,
    MarginLoan,
    MarginMode,
    MarginTier,
    OrderSide,
    OrderType,
    User,
)
from app.services import kyc, ledger, margin, pubsub
from app.services.kyc import KycRequired
from app.services.margin import MarginError
from app.services.pricing import usd_price_of

router = APIRouter(prefix="/margin", tags=["margin"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad number in {field}") from None


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


async def _asset(db: AsyncSession, symbol: str) -> Asset:
    a = (await db.execute(select(Asset).where(Asset.symbol == symbol.upper()))).scalar_one_or_none()
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown asset {symbol!r}")
    return a


async def _market(db: AsyncSession, symbol: str) -> Market:
    m = (await db.execute(select(Market).where(Market.symbol == symbol.upper()))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown market {symbol!r}")
    return m


async def _resolve_account(db, user_id, mode, symbol):
    acct = await margin.get_account(db, user_id=user_id, mode=mode, symbol=symbol)
    if acct is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such margin account — open one first")
    return acct


# --- schemas --------------------------------------------------------------------------------------

class OpenAccountRequest(BaseModel):
    mode: MarginMode = MarginMode.CROSS
    symbol: str | None = None
    tier: MarginTier = MarginTier.CLASSIC
    leverage: str | None = None


class TransferRequest(BaseModel):
    mode: MarginMode = MarginMode.CROSS
    symbol: str | None = None
    asset: str
    amount: str
    deposit: bool  # True: spot -> margin; False: margin -> spot


class BorrowRequest(BaseModel):
    mode: MarginMode = MarginMode.CROSS
    symbol: str | None = None
    asset: str
    amount: str


class RepayRequest(BaseModel):
    loan_id: int
    amount: str


class MarginOrderRequest(BaseModel):
    mode: MarginMode = MarginMode.CROSS
    symbol: str            # the pair, e.g. BTCUSDT
    side: OrderSide
    type: OrderType = OrderType.LIMIT
    quantity: str
    price: str | None = None
    auto_borrow: bool = True


class LoanRow(BaseModel):
    id: int
    asset: str
    principal: str
    accrued_interest: str
    owed: str
    hourly_rate: str


class MarginBalanceRow(BaseModel):
    asset: str
    available: str
    locked: str


class AccountResponse(BaseModel):
    id: int
    mode: str
    symbol: str | None
    tier: str
    max_leverage: str
    wallet: str
    gross_usd: str
    debt_usd: str
    equity_usd: str
    max_borrow_usd: str
    margin_level: str | None
    health: str
    loans: list[LoanRow]
    balances: list[MarginBalanceRow]


async def _account_response(db: AsyncSession, account) -> AccountResponse:
    state = await margin.account_state(db, account, usd_price_of)
    loans = await margin.open_loans(db, account)
    symbols = {a.id: a.symbol for a in (await db.execute(select(Asset))).scalars().all()}
    wallet_balances = await ledger.balances(db, account.user_id, wallet=account.wallet)
    return AccountResponse(
        id=account.id, mode=account.mode.value, symbol=account.symbol, tier=account.tier.value,
        max_leverage=_n(account.max_leverage), wallet=account.wallet,
        gross_usd=_n(state.gross_usd), debt_usd=_n(state.debt_usd), equity_usd=_n(state.equity_usd),
        max_borrow_usd=_n(state.max_borrow_usd),
        margin_level=(_n(state.margin_level) if state.margin_level is not None else None),
        health=margin.health_status(state.margin_level),
        loans=[
            LoanRow(id=ln.id, asset=symbols.get(ln.asset_id, "?"), principal=_n(ln.principal),
                    accrued_interest=_n(ln.accrued_interest), owed=_n(ln.owed), hourly_rate=_n(ln.hourly_rate))
            for ln in loans
        ],
        balances=[MarginBalanceRow(asset=b.symbol, available=_n(b.available), locked=_n(b.locked))
                  for b in wallet_balances],
    )


# --- routes ---------------------------------------------------------------------------------------

@router.post("/account", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def open_account(body: OpenAccountRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        account = await margin.open_account(
            db, user_id=user.id, mode=body.mode, symbol=body.symbol, tier=body.tier,
            leverage=_dec(body.leverage, "leverage") if body.leverage else None,
        )
    except MarginError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _account_response(db, account)


@router.get("/account", response_model=AccountResponse)
async def get_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    mode: MarginMode = Query(MarginMode.CROSS),
    symbol: str | None = Query(None),
):
    account = await _resolve_account(db, user.id, mode, symbol)
    return await _account_response(db, account)


@router.post("/transfer", response_model=AccountResponse)
async def transfer(body: TransferRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _resolve_account(db, user.id, body.mode, body.symbol)
    asset = await _asset(db, body.asset)
    try:
        await margin.transfer_collateral(db, account=account, asset_id=asset.id,
                                         amount=_dec(body.amount, "amount"), deposit=body.deposit)
    except MarginError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _account_response(db, account)


@router.post("/borrow", response_model=AccountResponse)
async def borrow(body: BorrowRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await _resolve_account(db, user.id, body.mode, body.symbol)
    asset = await _asset(db, body.asset)
    try:
        await margin.borrow(db, account=account, asset_id=asset.id, amount=_dec(body.amount, "amount"),
                            price_of=usd_price_of, now=_now())
    except MarginError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _account_response(db, account)


@router.post("/repay", response_model=AccountResponse)
async def repay(body: RepayRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    loan = await db.get(MarginLoan, body.loan_id)
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "loan not found")
    account = await db.get(MarginAccount, loan.margin_account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "loan not found")
    try:
        await margin.repay(db, account=account, loan=loan, amount=_dec(body.amount, "amount"))
    except MarginError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _account_response(db, account)


@router.post("/order", status_code=status.HTTP_201_CREATED)
async def place_order(body: MarginOrderRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await kyc.assert_approved(db, user.id)
    except KycRequired as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    account = await _resolve_account(db, user.id, body.mode, body.symbol if body.mode is MarginMode.ISOLATED else None)
    market = await _market(db, body.symbol)
    try:
        placed = await margin.place_margin_order(
            db, account=account, market=market, side=body.side, order_type=body.type,
            quantity=_dec(body.quantity, "quantity"),
            price=_dec(body.price, "price") if body.price else None,
            price_of=usd_price_of, now=_now(), auto_borrow=body.auto_borrow,
        )
    except MarginError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    pubsub.publish(pubsub.market_channel(market.symbol))
    o = placed.order
    return {"id": o.id, "symbol": market.symbol, "side": o.side.value, "type": o.type.value,
            "quantity": _n(o.quantity), "filled_quantity": _n(o.filled_quantity), "status": o.status.value,
            "wallet": o.wallet}


@router.post("/dev/liquidate")
async def dev_liquidate(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    symbol: str = Query(..., description="market to flatten liquidatable positions on"),
) -> dict[str, list[int]]:
    """Run one liquidation sweep against live prices for a market. Dev only."""
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "dev-only endpoint")
    market = await _market(db, symbol)
    liquidated: list[int] = []
    for account in await margin.liquidatable_accounts(db, usd_price_of):
        if account.mode is MarginMode.ISOLATED and account.symbol != market.symbol:
            continue
        if await margin.liquidate(db, account=account, market=market, price_of=usd_price_of, now=_now()):
            liquidated.append(account.id)
    await db.commit()
    pubsub.publish(pubsub.market_channel(market.symbol))
    return {"liquidated": liquidated}
