"""Sub-account endpoints: create, list (with value + balances), and transfer to/from the master."""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services import ledger, subaccounts
from app.services.pricing import usd_price_of
from app.services.subaccounts import SubAccountError

router = APIRouter(prefix="/subaccounts", tags=["subaccounts"])


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


class BalanceRow(BaseModel):
    asset: str
    available: str
    locked: str


class SubRow(BaseModel):
    id: int
    label: str
    created_at: str
    value_usd: str
    balances: list[BalanceRow]


class CreateRequest(BaseModel):
    label: str


class TransferRequest(BaseModel):
    sub_id: int
    asset: str
    amount: str
    to_sub: bool  # True: master → sub; False: sub → master


async def _row(db: AsyncSession, sub: User) -> SubRow:
    bals = await ledger.balances(db, sub.id)
    value = await subaccounts.portfolio_usd(db, sub.id, usd_price_of)
    return SubRow(
        id=sub.id, label=sub.full_name, created_at=sub.created_at.isoformat(), value_usd=_n(value),
        balances=[BalanceRow(asset=b.symbol, available=_n(b.available), locked=_n(b.locked)) for b in bals],
    )


@router.get("", response_model=list[SubRow])
async def list_subaccounts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    subs = await subaccounts.list_subs(db, user.id)
    return [await _row(db, s) for s in subs]


@router.post("", response_model=SubRow, status_code=status.HTTP_201_CREATED)
async def create_subaccount(body: CreateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        sub = await subaccounts.create(db, master=user, label=body.label)
    except SubAccountError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _row(db, sub)


@router.post("/transfer", response_model=list[SubRow])
async def transfer(body: TransferRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        amount = Decimal(body.amount)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad amount") from None
    try:
        await subaccounts.transfer(db, master=user, sub_id=body.sub_id, asset_symbol=body.asset,
                                   amount=amount, to_sub=body.to_sub)
    except SubAccountError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    subs = await subaccounts.list_subs(db, user.id)
    return [await _row(db, s) for s in subs]
