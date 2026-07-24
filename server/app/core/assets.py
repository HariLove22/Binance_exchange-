"""Supported assets and their scales.

Kept in code (not a table) while the list is tiny and changes with deploys. The `scale` is
the number of decimal places tracked internally — an asset's minimum unit. Every stored
amount is an integer count of that unit (satoshis for BTC, paise for INR).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    scale: int


ASSETS: dict[str, Asset] = {
    "BTC": Asset("BTC", "Bitcoin", 8),
    "ETH": Asset("ETH", "Ethereum", 8),
    "USDT": Asset("USDT", "Tether", 8),
    "INR": Asset("INR", "Indian Rupee", 2),
}

# Assets a new user gets an account row for, in display order.
DEFAULT_ASSETS = ["BTC", "ETH", "USDT", "INR"]


class UnknownAsset(ValueError):
    pass


def get_asset(symbol: str) -> Asset:
    asset = ASSETS.get(symbol.upper())
    if asset is None:
        raise UnknownAsset(f"unknown asset: {symbol}")
    return asset


def split_pair(pair: str) -> tuple[Asset, Asset]:
    """"BTC/USDT" -> (BTC, USDT). Quantities are in the base asset, prices in the quote."""
    base, sep, quote = pair.partition("/")
    if not sep:
        raise UnknownAsset(f"malformed pair: {pair}")
    return get_asset(base), get_asset(quote)
