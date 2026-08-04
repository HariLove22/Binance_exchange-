"""Token factory: create a coin as a synthetic ledger asset and mint its supply to the creator.

A launched token never touches a chain — it is an Asset(custodial=False), so it exists only as a
ledger balance, can't be withdrawn, and isn't reconciled against custody. The whole supply is minted
to the creator in one balanced transaction (credit from EXTERNAL, same path convert.py uses for a
synthetic mint), so money is conserved.
"""

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetKind, LaunchedToken, OfferingType
from app.services import ledger

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}$")
MAX_SUPPLY = Decimal("1000000000000")  # 1e12 — a sane ceiling; ponytail: raise if a real launch needs it


class LaunchError(Exception):
    """A token launch was refused. Safe to surface to a caller."""


async def launch(
    db: AsyncSession,
    *,
    creator_id: int,
    symbol: str,
    name: str,
    total_supply: Decimal,
    purpose: str = "",
    target_audience: str = "",
    offering_type: OfferingType = OfferingType.ICO,
) -> LaunchedToken:
    """Create a synthetic token and mint its whole supply to the creator's spot wallet."""
    symbol = symbol.upper().strip()
    if not SYMBOL_RE.match(symbol):
        raise LaunchError("symbol must be 2-12 uppercase letters/digits")
    if total_supply <= 0 or total_supply > MAX_SUPPLY:
        raise LaunchError(f"total supply must be between 0 and {MAX_SUPPLY}")
    if not name.strip():
        raise LaunchError("name is required")

    exists = (await db.execute(select(Asset).where(Asset.symbol == symbol))).scalar_one_or_none()
    if exists is not None:
        raise LaunchError(f"symbol {symbol} is already listed")

    asset = Asset(
        symbol=symbol, name=name.strip(), kind=AssetKind.CRYPTO, scale=18,
        enabled=True, custodial=False,  # synthetic — no chain, not withdrawable
    )
    db.add(asset)
    await db.flush()

    # Mint the full supply to the creator (credit from EXTERNAL — balances to zero).
    await ledger.credit(
        db, user_id=creator_id, asset_id=asset.id, amount=total_supply,
        kind=ledger.TransactionKind.ADJUSTMENT,
        idempotency_key=f"token-mint:{asset.id}",
        reference=f"launch {symbol}",
    )

    token = LaunchedToken(
        asset_id=asset.id, creator_id=creator_id, total_supply=total_supply,
        purpose=purpose.strip()[:500], target_audience=target_audience.strip()[:300],
        offering_type=offering_type,
    )
    db.add(token)
    await db.flush()
    return token
