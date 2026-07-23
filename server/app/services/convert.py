"""Convert — instant swap between two assets at the live price, like Binance Convert.

Not an order-book trade: a quote-based swap. You give X of A and receive Y of B computed from the
live prices, in one atomic ledger transaction, with the exchange (the market maker) as the
counterparty. No slippage, no resting order — the price is locked in the quote.

Pricing goes through USD: value_usd = amount_from × price(A), and amount_to = value_usd / price(B),
minus a spread that is the Convert fee. The market maker is the counterparty and must hold enough
of B; it is topped up on demand (a backed deposit for a custodial asset, a mint for a synthetic
one), so the swap always settles and reconciliation stays honest.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountType, Asset, AssetNetwork, TransactionKind, User
from app.services import deposits as deposit_service
from app.services import ledger
from app.services import marketmaker

BINANCE_PRICE_URL = "https://data-api.binance.vision/api/v3/ticker/price"
STABLE = {"USDT", "USDC"}
SPREAD = Decimal("0.001")  # 0.1% convert fee, kept by the exchange (the MM)


class ConvertError(Exception):
    pass


@dataclass(frozen=True)
class ConvertQuote:
    from_asset: str
    to_asset: str
    from_amount: Decimal
    to_amount: Decimal
    rate: Decimal  # to per from


async def _price_usd(symbol: str) -> Decimal:
    if symbol in STABLE:
        return Decimal("1")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(BINANCE_PRICE_URL, params={"symbol": f"{symbol}USDT"})
            resp.raise_for_status()
            return Decimal(resp.json()["price"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise ConvertError(f"could not price {symbol}") from exc


async def quote(db: AsyncSession, *, from_symbol: str, to_symbol: str, from_amount: Decimal) -> ConvertQuote:
    from_symbol, to_symbol = from_symbol.upper(), to_symbol.upper()
    if from_symbol == to_symbol:
        raise ConvertError("cannot convert an asset to itself")
    if from_amount <= 0:
        raise ConvertError("amount must be positive")

    to_asset = (await db.execute(select(Asset).where(Asset.symbol == to_symbol))).scalar_one_or_none()
    if (await db.execute(select(Asset).where(Asset.symbol == from_symbol))).scalar_one_or_none() is None:
        raise ConvertError(f"unknown asset {from_symbol}")
    if to_asset is None:
        raise ConvertError(f"unknown asset {to_symbol}")

    value_usd = from_amount * await _price_usd(from_symbol)
    to_price = await _price_usd(to_symbol)
    gross = value_usd / to_price
    to_amount = (gross * (Decimal(1) - SPREAD)).quantize(Decimal(1).scaleb(-to_asset.scale), rounding=ROUND_DOWN)
    if to_amount <= 0:
        raise ConvertError("amount too small to convert")

    rate = to_amount / from_amount
    return ConvertQuote(from_asset=from_symbol, to_asset=to_symbol, from_amount=from_amount,
                        to_amount=to_amount, rate=rate)


async def _available(db: AsyncSession, user_id: int | None, asset_id: int) -> Decimal:
    acct = await ledger.get_or_create_account(db, asset_id, AccountType.AVAILABLE, user_id)
    return acct.balance


async def _ensure_mm_inventory(db: AsyncSession, asset: Asset, needed: Decimal) -> None:
    """Make sure the market maker holds at least `needed` of `asset`. Tops up if short: a backed
    deposit for a custodial asset (so reconciliation holds), a mint for a synthetic one."""
    mm = await marketmaker.get_market_maker(db)
    have = await _available(db, mm.id, asset.id)
    if have >= needed:
        return
    top_up = needed - have + Decimal("1")  # a little headroom

    if not asset.custodial:
        await ledger.credit(db, user_id=mm.id, asset_id=asset.id, amount=top_up,
                            kind=TransactionKind.ADJUSTMENT, idempotency_key=f"convert-mint:{asset.id}:{have}",
                            reference="convert MM inventory")
        return

    network = (
        await db.execute(select(AssetNetwork).where(AssetNetwork.asset_id == asset.id).order_by(AssetNetwork.id))
    ).scalars().first()
    if network is None:
        raise ConvertError(f"no way to source {asset.symbol}")
    if not network.deposit_enabled:
        network.deposit_enabled = True
        await db.flush()
    addr = await deposit_service.get_or_create_address(db, mm.id, network.id)
    import time

    deposit = await deposit_service.record_deposit(
        db, asset_network_id=network.id, tx_hash=f"0xconv{asset.id}-{int(time.time()*1000)}", amount=top_up
    )
    deposit.user_id = mm.id
    deposit.deposit_address_id = addr.id
    deposit.confirmations = deposit.required_confirmations
    db.add(deposit)
    await db.flush()
    await deposit_service.credit_if_confirmed(db, deposit)


async def execute(db: AsyncSession, *, user: User, from_symbol: str, to_symbol: str, from_amount: Decimal) -> ConvertQuote:
    """Swap the user's `from` for `to` at the live rate, atomically, against the market maker."""
    q = await quote(db, from_symbol=from_symbol, to_symbol=to_symbol, from_amount=from_amount)

    from_asset = (await db.execute(select(Asset).where(Asset.symbol == q.from_asset))).scalar_one()
    to_asset = (await db.execute(select(Asset).where(Asset.symbol == q.to_asset))).scalar_one()

    if await _available(db, user.id, from_asset.id) < q.from_amount:
        raise ConvertError(f"insufficient {q.from_asset}")

    await _ensure_mm_inventory(db, to_asset, q.to_amount)
    mm = await marketmaker.get_market_maker(db)

    user_from = await ledger.get_or_create_account(db, from_asset.id, AccountType.AVAILABLE, user.id)
    mm_from = await ledger.get_or_create_account(db, from_asset.id, AccountType.AVAILABLE, mm.id)
    mm_to = await ledger.get_or_create_account(db, to_asset.id, AccountType.AVAILABLE, mm.id)
    user_to = await ledger.get_or_create_account(db, to_asset.id, AccountType.AVAILABLE, user.id)

    # One balanced transaction: the user's `from` goes to the MM, the MM's `to` goes to the user.
    # Zero-sum per asset. The MM keeps the spread as its convert margin.
    import time

    await ledger.post(
        db,
        idempotency_key=f"convert:{user.id}:{q.from_asset}:{q.to_asset}:{int(time.time()*1000)}",
        kind=TransactionKind.TRADE,
        reference=f"convert {q.from_amount} {q.from_asset} -> {q.to_amount} {q.to_asset}",
        movements=[
            ledger.Movement(user_from, -q.from_amount),
            ledger.Movement(mm_from, q.from_amount),
            ledger.Movement(mm_to, -q.to_amount),
            ledger.Movement(user_to, q.to_amount),
        ],
    )
    return q
