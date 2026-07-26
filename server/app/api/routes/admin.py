"""Operator endpoints — admin only.

The credit endpoint is the loaded one: it puts money into a user's account. It does so through the
**real deposit flow**, not a raw ledger mint, so custody "sees" a matching on-chain deposit and
reconciliation stays balanced. A raw mint would show up as unbacked — which is correct, but makes
the admin tool look like it broke the books. Refused outside development regardless.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import admin_user
from app.core.config import settings
from app.core.db import get_db
from app.models import (
    Account,
    AccountType,
    Asset,
    AssetNetwork,
    Chain,
    User,
    UserRole,
)
from app.services import deposits as deposit_service
from app.services import reconcile as reconcile_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(admin_user)])


class AdminUserRow(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    is_verified: bool
    is_active: bool
    asset_count: int


@router.get("/users", response_model=list[AdminUserRow])
async def list_users(limit: int = Query(default=100, le=500), db: AsyncSession = Depends(get_db)):
    counts = dict(
        (
            await db.execute(
                select(Account.user_id, func.count())
                .where(Account.user_id.isnot(None), Account.balance > 0,
                       Account.account_type == AccountType.AVAILABLE)
                .group_by(Account.user_id)
            )
        ).all()
    )
    users = (await db.execute(select(User).order_by(User.id.desc()).limit(limit))).scalars().all()
    return [
        AdminUserRow(
            id=u.id, email=u.email, full_name=u.full_name, role=u.role,
            is_verified=u.is_verified, is_active=u.is_active, asset_count=counts.get(u.id, 0),
        )
        for u in users
    ]


class CreditRequest(BaseModel):
    user_id: int
    asset: str
    # A string, never a float. Parsing "0.1" into a double loses the value the operator typed.
    amount: str = Field(description='Decimal string, e.g. "1000.50"')
    chain: str | None = Field(default=None, description="Chain code; defaults to the first network")


class CreditResponse(BaseModel):
    deposit_id: int
    user_id: int
    asset: str
    amount: str
    status: str


@router.post("/credit", response_model=CreditResponse, status_code=status.HTTP_201_CREATED)
async def credit_user(
    body: CreditRequest,
    admin: User = Depends(admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Add test funds to a user, through the deposit flow so reconciliation stays balanced.

    Refused outside development: in production this would create balances no real deposit backs.
    """
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "admin credit is disabled in production — funds must arrive through a real deposit",
        )

    try:
        amount = Decimal(body.amount)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad amount {body.amount!r}") from None
    if amount <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "amount must be positive")

    target = await db.get(User, body.user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown user {body.user_id}")

    query = (
        select(AssetNetwork)
        .join(Asset, Asset.id == AssetNetwork.asset_id)
        .where(Asset.symbol == body.asset.upper())
    )
    if body.chain:
        query = query.join(Chain, Chain.id == AssetNetwork.chain_id).where(Chain.code == body.chain.upper())
    network = (await db.execute(query.order_by(AssetNetwork.id))).scalars().first()
    if network is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no network for {body.asset!r}")

    asset = await db.get(Asset, network.asset_id)
    if amount.as_tuple().exponent < -asset.scale:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{body.amount} has more precision than {asset.symbol} allows (scale {asset.scale})",
        )

    if not network.deposit_enabled:
        network.deposit_enabled = True
        await db.flush()

    # Simulate a confirmed on-chain deposit — the same path a real deposit takes.
    address = await deposit_service.get_or_create_address(db, target.id, network.id)
    import time

    tx_hash = f"0xadmin{admin.id}-{target.id}-{int(time.time() * 1000)}"
    deposit = await deposit_service.record_deposit(
        db, asset_network_id=network.id, tx_hash=tx_hash, amount=amount
    )
    deposit.user_id = target.id
    deposit.deposit_address_id = address.id
    deposit.confirmations = deposit.required_confirmations
    db.add(deposit)
    await db.flush()
    await deposit_service.credit_if_confirmed(db, deposit)
    await db.commit()

    return CreditResponse(
        deposit_id=deposit.id, user_id=target.id, asset=asset.symbol,
        amount=body.amount, status=deposit.status.value,
    )


class ReconciliationRow(BaseModel):
    asset: str
    trial_balance: str
    ledger_external: str
    custody_onchain: str
    balanced: bool


@router.get("/reconcile", response_model=list[ReconciliationRow])
async def reconcile(db: AsyncSession = Depends(get_db)):
    """Ledger vs custody, system-wide. Every row must be balanced."""
    return [ReconciliationRow(**vars(r)) for r in await reconcile_service.reconcile(db)]
