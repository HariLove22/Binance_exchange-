"""Account center: an overview of the user's trading accounts, and the demo (paper) account.

The overview answers "what accounts do I have and what are they worth" across Spot, Cross Margin, and
Demo. The demo endpoints run a risk-free sandbox — virtual funds, live prices, no real-money impact.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import MarginMode, OrderSide, User
from app.services import demo, ledger, margin
from app.services.demo import DemoError
from app.services.pricing import usd_price_of

router = APIRouter(prefix="/account", tags=["account"])


def _n(d: Decimal) -> str:
    return f"{d.normalize():f}"


def _dec(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad number in {field}") from None


async def _spot_usd(db: AsyncSession, user_id: int) -> Decimal:
    total = Decimal(0)
    for b in await ledger.balances(db, user_id):  # SPOT wallet
        px = await usd_price_of(b.symbol)
        if px is not None:
            total += b.total * px
    return total


# --- schemas --------------------------------------------------------------------------------------

class MarginSummary(BaseModel):
    open: bool
    equity_usd: str | None = None
    margin_level: str | None = None
    health: str | None = None
    max_leverage: str | None = None


class DemoSummary(BaseModel):
    exists: bool
    total_usd: str | None = None


class Overview(BaseModel):
    spot_usd: str
    margin: MarginSummary
    demo: DemoSummary


class DemoHoldingRow(BaseModel):
    symbol: str
    quantity: str
    usd_value: str


class DemoResponse(BaseModel):
    exists: bool
    total_usd: str
    holdings: list[DemoHoldingRow]


class DemoTradeRequest(BaseModel):
    base: str            # e.g. BTC
    side: OrderSide
    quantity: str


# --- overview -------------------------------------------------------------------------------------

@router.get("/overview", response_model=Overview)
async def overview(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    spot = await _spot_usd(db, user.id)

    cross = await margin.get_account(db, user_id=user.id, mode=MarginMode.CROSS, symbol=None)
    if cross is None:
        m = MarginSummary(open=False)
    else:
        st = await margin.account_state(db, cross, usd_price_of)
        m = MarginSummary(open=True, equity_usd=_n(st.equity_usd),
                          margin_level=(_n(st.margin_level) if st.margin_level is not None else None),
                          health=margin.health_status(st.margin_level), max_leverage=_n(cross.max_leverage))

    dacct = await demo.get_account(db, user.id)
    if dacct is None:
        d = DemoSummary(exists=False)
    else:
        d = DemoSummary(exists=True, total_usd=(await demo.portfolio(db, dacct, usd_price_of))["total_usd"].__str__())

    return Overview(spot_usd=_n(spot), margin=m, demo=d)


# --- demo -----------------------------------------------------------------------------------------

async def _demo_response(db: AsyncSession, account) -> DemoResponse:
    p = await demo.portfolio(db, account, usd_price_of)
    return DemoResponse(
        exists=True, total_usd=str(p["total_usd"]),
        holdings=[DemoHoldingRow(symbol=h["symbol"], quantity=_n(h["quantity"]), usd_value=str(h["usd_value"]))
                  for h in p["holdings"]],
    )


@router.get("/demo", response_model=DemoResponse)
async def get_demo(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await demo.get_account(db, user.id)
    if account is None:
        return DemoResponse(exists=False, total_usd="0", holdings=[])
    return await _demo_response(db, account)


@router.post("/demo", response_model=DemoResponse, status_code=status.HTTP_201_CREATED)
async def create_demo(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        account = await demo.create_account(db, user.id)
    except DemoError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _demo_response(db, account)


@router.post("/demo/reset", response_model=DemoResponse)
async def reset_demo(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await demo.get_account(db, user.id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no demo account")
    await demo.reset_account(db, account)
    await db.commit()
    return await _demo_response(db, account)


@router.post("/demo/trade", response_model=DemoResponse)
async def demo_trade(body: DemoTradeRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    account = await demo.get_account(db, user.id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "create a demo account first")
    try:
        await demo.trade(db, account=account, base_symbol=body.base, side=body.side,
                         quantity=_dec(body.quantity, "quantity"), price_of=usd_price_of)
    except DemoError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return await _demo_response(db, account)
