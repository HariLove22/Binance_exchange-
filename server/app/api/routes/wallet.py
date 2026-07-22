"""What a user holds.

Balances only for now — this is what makes the dashboard's `0.00` real. Deposit addresses and
withdrawals need a custody provider, which does not exist yet (see docs/03-wallet.md).
"""

from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.services import ledger

router = APIRouter(prefix="/wallet", tags=["wallet"])


class BalanceResponse(BaseModel):
    asset: str
    scale: int
    # Strings, not JSON numbers — a naive client parses a number into a double and loses the
    # precision the ledger stores in NUMERIC(36,18). The same reason Binance returns strings.
    available: str
    locked: str
    total: str


def _fmt(value: Decimal, scale: int) -> str:
    return f"{value.quantize(Decimal(1).scaleb(-scale)):f}"


@router.get("/balances", response_model=list[BalanceResponse])
async def balances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BalanceResponse]:
    """Every asset this user holds.

    `available` is spendable; `locked` is reserved against open orders. Both are the user's money
    — locked funds are not gone, just not spendable twice. A UI that shows only `available` after
    an order is placed reads as "my money disappeared", so both are always returned together.
    """
    return [
        BalanceResponse(
            asset=b.symbol,
            scale=b.scale,
            available=_fmt(b.available, b.scale),
            locked=_fmt(b.locked, b.scale),
            total=_fmt(b.total, b.scale),
        )
        for b in await ledger.balances(db, user.id)
    ]
