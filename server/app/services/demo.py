"""Demo (paper) trading service. Virtual funds, live prices, zero real-money impact.

A demo account starts with virtual USDT. A trade fills instantly at the injected reference price — a
buy spends quote and adds base, a sell does the reverse — with a small simulated fee so the practice
feels real. Nothing here touches the ledger, custody, or the trial balance: it is a sandbox.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DemoAccount, DemoHolding, OrderSide

PriceOf = Callable[[str], Awaitable[Decimal | None]]

STARTING_USDT = Decimal("10000")   # virtual funds granted on creation / reset
QUOTE = "USDT"                       # demo settles everything in virtual USDT
FEE_RATE = Decimal("0.001")          # 0.1% simulated taker fee


class DemoError(Exception):
    """A demo action was refused. Safe to surface to a caller."""


async def get_account(db: AsyncSession, user_id: int) -> DemoAccount | None:
    return (await db.execute(select(DemoAccount).where(DemoAccount.user_id == user_id))).scalar_one_or_none()


async def _holding(db: AsyncSession, account: DemoAccount, symbol: str) -> DemoHolding:
    for h in account.holdings:
        if h.symbol == symbol:
            return h
    h = DemoHolding(demo_account_id=account.id, symbol=symbol, quantity=Decimal(0))
    db.add(h)
    account.holdings.append(h)
    await db.flush()
    return h


async def create_account(db: AsyncSession, user_id: int) -> DemoAccount:
    if await get_account(db, user_id) is not None:
        raise DemoError("demo account already exists")
    account = DemoAccount(user_id=user_id)
    db.add(account)
    await db.flush()
    seed = DemoHolding(demo_account_id=account.id, symbol=QUOTE, quantity=STARTING_USDT)
    db.add(seed)
    await db.flush()
    await db.refresh(account)
    return account


async def reset_account(db: AsyncSession, account: DemoAccount) -> DemoAccount:
    """Wipe all holdings and re-grant the starting virtual USDT."""
    for h in list(account.holdings):
        await db.delete(h)
    account.holdings.clear()
    await db.flush()
    seed = DemoHolding(demo_account_id=account.id, symbol=QUOTE, quantity=STARTING_USDT)
    db.add(seed)
    await db.flush()
    await db.refresh(account)
    return account


def _floor(value: Decimal, places: int = 8) -> Decimal:
    step = Decimal(1).scaleb(-places)
    return value.quantize(step, rounding=ROUND_DOWN)


async def trade(
    db: AsyncSession,
    *,
    account: DemoAccount,
    base_symbol: str,
    side: OrderSide,
    quantity: Decimal,
    price_of: PriceOf,
) -> DemoHolding:
    """Fill a market order at the live price. Buy: spend USDT for base. Sell: base for USDT."""
    base_symbol = base_symbol.upper()
    if base_symbol == QUOTE:
        raise DemoError("choose a base asset other than USDT")
    if quantity <= 0:
        raise DemoError("quantity must be positive")

    price = await price_of(base_symbol)
    if price is None or price <= 0:
        raise DemoError(f"no live price for {base_symbol}")

    notional = _floor(price * quantity, 8)
    fee = _floor(notional * FEE_RATE, 8)
    usdt = await _holding(db, account, QUOTE)
    base = await _holding(db, account, base_symbol)

    if side is OrderSide.BUY:
        cost = notional + fee
        if usdt.quantity < cost:
            raise DemoError(f"not enough virtual USDT: need {cost}, have {usdt.quantity}")
        usdt.quantity -= cost
        base.quantity += quantity
    else:
        if base.quantity < quantity:
            raise DemoError(f"not enough {base_symbol}: need {quantity}, have {base.quantity}")
        base.quantity -= quantity
        usdt.quantity += notional - fee
    return base


async def portfolio(db: AsyncSession, account: DemoAccount, price_of: PriceOf) -> dict:
    """Holdings plus their USD value and the account total, for display."""
    rows = []
    total = Decimal(0)
    for h in sorted(account.holdings, key=lambda x: x.symbol):
        if h.quantity <= 0 and h.symbol != QUOTE:
            continue
        px = Decimal("1") if h.symbol == QUOTE else (await price_of(h.symbol) or Decimal(0))
        value = _floor(h.quantity * px, 2)
        total += value
        rows.append({"symbol": h.symbol, "quantity": h.quantity, "usd_value": value})
    return {"holdings": rows, "total_usd": _floor(total, 2)}
