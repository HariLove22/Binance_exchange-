"""Perpetual futures endpoints: collateral, open/close positions, account with live PnL."""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import PositionSide, User, WALLET_FUTURES
from app.services import futures, kyc, ledger, marketmaker
from app.services.futures import FuturesError
from app.services.kyc import KycRequired

router = APIRouter(prefix="/futures", tags=["futures"])

# Mark price for a perp symbol is the live index from the public feed.
mark_of = marketmaker.fetch_reference_price


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
    mark: str | None
    unrealized_pnl: str | None
    roe: str | None
    liquidation_price: str


class AccountResponse(BaseModel):
    balance_usdt: str
    balances: dict[str, str]  # futures-wallet available balance per asset symbol
    positions: list[PositionRow]


async def _positions(db: AsyncSession, user_id: int) -> list[PositionRow]:
    rows: list[PositionRow] = []
    for p in await futures.open_positions(db, user_id):
        mark = await mark_of(p.symbol)
        st = futures.position_state(p, mark) if mark else None
        rows.append(PositionRow(
            id=p.id, symbol=p.symbol, side=p.side.value, inverse=p.inverse, margin_asset=p.margin_asset,
            size=_n(p.size), entry_price=_n(p.entry_price),
            leverage=_n(p.leverage), margin=_n(p.margin),
            mark=_n(mark) if mark else None,
            unrealized_pnl=_n(st["unrealized_pnl"]) if st else None,
            roe=_n(st["roe"]) if st else None,
            liquidation_price=_n(futures.liquidation_price(p)),
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
            leverage=_dec(body.leverage, "leverage"), price_of=mark_of, inverse=body.inverse,
        )
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"id": pos.id, "symbol": pos.symbol, "side": pos.side.value, "entry_price": _n(pos.entry_price),
            "size": _n(pos.size), "margin": _n(pos.margin), "margin_asset": pos.margin_asset}


@router.post("/close/{position_id}")
async def close(position_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        pos = await futures.close_position(db, user_id=user.id, position_id=position_id, price_of=mark_of)
    except FuturesError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"id": pos.id, "status": pos.status.value, "close_price": _n(pos.close_price or Decimal(0)),
            "realized_pnl": _n(pos.realized_pnl)}
