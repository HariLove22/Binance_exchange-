"""Wallet endpoints: read balances, and (in development only) mint test funds.

Phase 1 is paper trading — there is no custody and no real deposits. The faucet stands in for
a deposit so the trading flow can be exercised end to end.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.assets import DEFAULT_ASSETS, UnknownAsset, get_asset
from app.core.config import settings
from app.core.db import get_db
from app.core.money import MoneyError, format_money, from_scaled_int, to_scaled_int
from app.models.user import User
from app.models.wallet import AVAILABLE, EXTERNAL, LOCKED
from app.schemas.wallet import BalanceOut, BalancesResponse, FaucetRequest, FaucetResponse
from app.services.ledger import LedgerError, get_balances, get_or_create_account, post_transaction

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _fmt(units: int, scale: int) -> str:
    return format_money(from_scaled_int(units, scale), scale)


@router.get("/balances", response_model=BalancesResponse)
async def balances(
    current: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> BalancesResponse:
    held = await get_balances(db, current.id)

    out: list[BalanceOut] = []
    for symbol in DEFAULT_ASSETS:
        asset = get_asset(symbol)
        row = held.get(symbol, {"available": 0, "locked": 0})
        out.append(
            BalanceOut(
                asset=asset.symbol,
                name=asset.name,
                available=_fmt(row["available"], asset.scale),
                locked=_fmt(row["locked"], asset.scale),
                total=_fmt(row["available"] + row["locked"], asset.scale),
            )
        )
    return BalancesResponse(balances=out)


@router.post("/faucet", response_model=FaucetResponse, status_code=status.HTTP_201_CREATED)
async def faucet(
    body: FaucetRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FaucetResponse:
    if not settings.faucet_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The faucet is disabled")

    try:
        asset = get_asset(body.asset)
    except UnknownAsset:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown asset: {body.asset}")

    try:
        units = to_scaled_int(body.amount, asset.scale)
        max_units = to_scaled_int(settings.faucet_max_amount, asset.scale)
    except MoneyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    if units <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be greater than zero")
    if units > max_units:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Amount exceeds the faucet limit of {settings.faucet_max_amount}"
        )

    # Money enters the system from EXTERNAL: that account goes negative by exactly what the
    # user gains, so the ledger still sums to zero for this asset.
    external = await get_or_create_account(db, asset=asset.symbol, account_type=EXTERNAL)
    user_available = await get_or_create_account(
        db, asset=asset.symbol, account_type=AVAILABLE, user_id=current.id
    )
    # Create the LOCKED counterpart up front so trading can reserve funds later.
    await get_or_create_account(db, asset=asset.symbol, account_type=LOCKED, user_id=current.id)

    try:
        await post_transaction(
            db,
            kind="FAUCET",
            idempotency_key=f"faucet:{current.id}:{uuid.uuid4()}",
            legs=[(external, -units), (user_available, units)],
        )
    except LedgerError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    await db.commit()
    await db.refresh(user_available)

    return FaucetResponse(
        asset=asset.symbol,
        credited=_fmt(units, asset.scale),
        available=_fmt(user_available.balance, asset.scale),
    )
