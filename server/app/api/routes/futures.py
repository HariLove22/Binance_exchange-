"""Perpetual futures endpoints: collateral, open/close positions, account with live PnL."""

import datetime
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import Asset, KycApplication, KycStatus, PositionSide, User, WALLET_FUTURES
from app.services import futures, kyc, ledger, marketmaker
from app.services.futures import FuturesError
from app.services.kyc import KycRequired

router = APIRouter(prefix="/futures", tags=["futures"])

# Fills happen at the LAST price (raw index); PnL and liquidation use the smoothed MARK price.
last_of = futures.last_price
mark_of = futures.mark_price


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


def _dec(v: str, field: str) -> Decimal:
    try:
        return Decimal(v)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad number in {field}") from None


class TransferRequest(BaseModel):
    amount: str
    deposit: bool  # True: spot -> futures
    asset: str = "USDT"  # margin asset — USDT for USDT-M, a coin (BTC…) for COIN-M


class OrderRequest(BaseModel):
    symbol: str
    side: PositionSide
    size: str
    leverage: str
    inverse: bool = False  # True = COIN-M (coin-margined, inverse); size is USD notional


class PositionRow(BaseModel):
    id: int
    symbol: str
    side: str
    inverse: bool
    margin_asset: str
    size: str
    entry_price: str
    leverage: str
    margin: str
    mark: str | None      # smoothed mark price — drives PnL/liquidation
    last: str | None      # raw last/index price — where fills happen
    unrealized_pnl: str | None
    roe: str | None
    liquidation_price: str
    funding_accrued: str
    funding_rate: str


class AccountResponse(BaseModel):
    balance_usdt: str
    balances: dict[str, str]  # futures-wallet available balance per asset symbol
    positions: list[PositionRow]


async def _positions(db: AsyncSession, user_id: int) -> list[PositionRow]:
    rows: list[PositionRow] = []
    for p in await futures.open_positions(db, user_id):
        mark = await mark_of(p.symbol)
        last = await last_of(p.symbol)
        st = futures.position_state(p, mark) if mark else None
        rows.append(PositionRow(
            id=p.id, symbol=p.symbol, side=p.side.value, inverse=p.inverse, margin_asset=p.margin_asset,
            size=_n(p.size), entry_price=_n(p.entry_price),
            leverage=_n(p.leverage), margin=_n(p.margin),
            mark=_n(mark) if mark else None,
            last=_n(last) if last else None,
            unrealized_pnl=_n(st["unrealized_pnl"]) if st else None,
            roe=_n(st["roe"]) if st else None,
            liquidation_price=_n(futures.liquidation_price(p)),
            funding_accrued=_n(p.funding_accrued),
            funding_rate=_n(futures.FUNDING_RATE),
        ))
    return rows


async def _balances(db: AsyncSession, user_id: int) -> dict[str, str]:
    return {b.symbol: _n(b.available) for b in await ledger.balances(db, user_id, wallet=WALLET_FUTURES)}


async def _account(db: AsyncSession, user_id: int) -> AccountResponse:
    bals = await _balances(db, user_id)
    return AccountResponse(
        balance_usdt=bals.get("USDT", "0"), balances=bals, positions=await _positions(db, user_id)
    )


@router.get("/account", response_model=AccountResponse)
async def account(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _account(db, user.id)


@router.post("/dev/setup")
async def dev_setup(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Dev only: credit 50,000 test USDT to spot AND auto-approve KYC, so futures can be tried in one
    click without a real deposit or identity review. Refuses to run outside development."""
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "dev-only endpoint")

    # USDT for USDT-M, and a little BTC so COIN-M (coin-margined) can be tried too.
    for sym, amt in (("USDT", Decimal("50000")), ("BTC", Decimal("1"))):
        asset = (await db.execute(select(Asset).where(Asset.symbol == sym))).scalar_one_or_none()
        if asset is not None:
            await ledger.credit(db, user_id=user.id, asset_id=asset.id, amount=amt,
                                kind=ledger.TransactionKind.ADMIN_CREDIT, idempotency_key=f"fut-setup:{user.id}:{sym}:{uuid.uuid4()}")

    app_row = (await db.execute(select(KycApplication).where(KycApplication.user_id == user.id))).scalar_one_or_none()
    if app_row is None:
        db.add(KycApplication(
            user_id=user.id, status=KycStatus.APPROVED, legal_name=user.full_name or "Dev Tester",
            date_of_birth=datetime.date(1998, 1, 1), country="India", id_type="PASSPORT", id_number="DEVKYC",
        ))
    else:
        app_row.status = KycStatus.APPROVED
    await db.commit()
    return {"credited": "50000 USDT + 1 BTC", "kyc": "APPROVED"}


@router.post("/dev/apply-funding")
async def dev_apply_funding(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Dev only: charge one funding interval to every open position right now, instead of waiting 8h,
    so the funding mechanism can be seen in testing."""
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "dev-only endpoint")
    # Pretend a full interval has elapsed so every open position is due exactly once.
    now = datetime.datetime.now(datetime.timezone.utc) + futures.FUNDING_INTERVAL
    funded = await futures.apply_funding(db, now=now, price_of=mark_of)
    await db.commit()
    return {"funded": funded, "rate": _n(futures.FUNDING_RATE)}


@router.post("/transfer", response_model=AccountResponse)
async def transfer(body: TransferRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await futures.transfer_collateral(
            db, user_id=user.id, amount=_dec(body.amount, "amount"), deposit=body.deposit, asset=body.asset,
        )
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _account(db, user.id)


@router.post("/order", status_code=status.HTTP_201_CREATED)
async def open_order(body: OrderRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await kyc.assert_approved(db, user.id)
    except KycRequired as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    try:
        pos = await futures.open_position(
            db, user_id=user.id, symbol=body.symbol, side=body.side, size=_dec(body.size, "size"),
            leverage=_dec(body.leverage, "leverage"), price_of=last_of, inverse=body.inverse,
        )
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"id": pos.id, "symbol": pos.symbol, "side": pos.side.value, "entry_price": _n(pos.entry_price),
            "size": _n(pos.size), "margin": _n(pos.margin), "margin_asset": pos.margin_asset}


@router.post("/close/{position_id}")
async def close(position_id: int, size: str | None = None,
                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Close a position, or `size` of it (partial) when given as a query param."""
    try:
        pos = await futures.close_position(
            db, user_id=user.id, position_id=position_id, price_of=last_of,
            size=_dec(size, "size") if size is not None else None,
        )
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"id": pos.id, "status": pos.status.value, "close_price": _n(pos.close_price or Decimal(0)),
            "realized_pnl": _n(pos.realized_pnl), "size": _n(pos.size)}


class MarginRequest(BaseModel):
    amount: str
    add: bool  # True = add margin, False = remove


@router.post("/position/{position_id}/margin")
async def adjust_margin(position_id: int, body: MarginRequest,
                        user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        pos = await futures.adjust_margin(db, user_id=user.id, position_id=position_id,
                                          amount=_dec(body.amount, "amount"), add=body.add, price_of=mark_of)
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"id": pos.id, "margin": _n(pos.margin), "liquidation_price": _n(futures.liquidation_price(pos))}


class LeverageRequest(BaseModel):
    leverage: str


@router.post("/position/{position_id}/leverage")
async def set_leverage(position_id: int, body: LeverageRequest,
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        pos = await futures.set_leverage(db, user_id=user.id, position_id=position_id,
                                         leverage=_dec(body.leverage, "leverage"), price_of=mark_of)
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"id": pos.id, "leverage": _n(pos.leverage), "margin": _n(pos.margin),
            "liquidation_price": _n(futures.liquidation_price(pos))}
