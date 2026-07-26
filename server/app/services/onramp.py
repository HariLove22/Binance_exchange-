"""Fiat on-ramp: buy crypto with a fiat currency, the way Binance's "Buy Crypto" flow works.

You pick a payment currency (INR, USD, EUR…) and an amount, and receive crypto at the live price.
Under the hood it is a currency conversion followed by a credit: fiat -> USD (an FX rate) -> the
target asset (the live Binance price) -> the ledger.

Everything here is a mock stand-in for a real payment provider (MoonPay / Transak / a bank). There
is no actual fiat movement — a real provider would charge a card or take a bank transfer, and only
then would we credit. So this is dev-only, and it credits through the deposit flow so the crypto is
backed and reconciliation stays balanced. The FX rates are static placeholders, not a live feed.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetNetwork, Chain, User
from app.services import deposits as deposit_service

BINANCE_PRICE_URL = "https://data-api.binance.vision/api/v3/ticker/price"

# Units of the currency per 1 USD. Static placeholders — a real integration reads a live FX feed.
FIAT_RATES: dict[str, Decimal] = {
    "USD": Decimal("1"),
    "INR": Decimal("83.2"),
    "EUR": Decimal("0.92"),
    "GBP": Decimal("0.79"),
    "AED": Decimal("3.67"),
    "SGD": Decimal("1.35"),
}

FIAT_NAMES = {
    "USD": "US Dollar", "INR": "Indian Rupee", "EUR": "Euro",
    "GBP": "British Pound", "AED": "UAE Dirham", "SGD": "Singapore Dollar",
}

# Assets valued at 1 USD without a price lookup.
STABLE = {"USDT", "USDC"}


class OnrampError(Exception):
    pass


@dataclass(frozen=True)
class Quote:
    fiat: str
    fiat_amount: Decimal
    usd_amount: Decimal
    asset: str
    unit_price_usd: Decimal
    crypto_amount: Decimal


async def _asset_price_usd(symbol: str) -> Decimal:
    if symbol in STABLE:
        return Decimal("1")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(BINANCE_PRICE_URL, params={"symbol": f"{symbol}USDT"})
            resp.raise_for_status()
            return Decimal(resp.json()["price"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise OnrampError(f"could not price {symbol}") from exc


async def quote(db: AsyncSession, *, fiat: str, fiat_amount: Decimal, asset_symbol: str) -> Quote:
    fiat = fiat.upper()
    asset_symbol = asset_symbol.upper()
    if fiat not in FIAT_RATES:
        raise OnrampError(f"unsupported currency {fiat}")
    if fiat_amount <= 0:
        raise OnrampError("amount must be positive")

    asset = (await db.execute(select(Asset).where(Asset.symbol == asset_symbol))).scalar_one_or_none()
    if asset is None:
        raise OnrampError(f"unknown asset {asset_symbol}")

    usd = fiat_amount / FIAT_RATES[fiat]
    unit_price = await _asset_price_usd(asset_symbol)
    crypto = (usd / unit_price).quantize(Decimal(1).scaleb(-asset.scale), rounding=ROUND_DOWN)
    if crypto <= 0:
        raise OnrampError("amount too small for this asset")

    return Quote(
        fiat=fiat, fiat_amount=fiat_amount, usd_amount=usd,
        asset=asset_symbol, unit_price_usd=unit_price, crypto_amount=crypto,
    )


async def buy(db: AsyncSession, *, user: User, fiat: str, fiat_amount: Decimal, asset_symbol: str) -> Quote:
    """Convert fiat to crypto and credit it through the deposit flow (so it is backed)."""
    q = await quote(db, fiat=fiat, fiat_amount=fiat_amount, asset_symbol=asset_symbol)

    network = (
        await db.execute(
            select(AssetNetwork)
            .join(Asset, Asset.id == AssetNetwork.asset_id)
            .where(Asset.symbol == q.asset)
            .order_by(AssetNetwork.id)
        )
    ).scalars().first()
    if network is None:
        raise OnrampError(f"no network to credit {q.asset} on")
    if not network.deposit_enabled:
        network.deposit_enabled = True
        await db.flush()

    address = await deposit_service.get_or_create_address(db, user.id, network.id)
    import time

    tx_hash = f"0xonramp{user.id}-{int(time.time() * 1000)}"
    deposit = await deposit_service.record_deposit(
        db, asset_network_id=network.id, tx_hash=tx_hash, amount=q.crypto_amount
    )
    deposit.user_id = user.id
    deposit.deposit_address_id = address.id
    deposit.confirmations = deposit.required_confirmations
    db.add(deposit)
    await db.flush()
    await deposit_service.credit_if_confirmed(db, deposit)
    return q
