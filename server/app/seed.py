"""Seed reference data: chains, assets, and the networks joining them.

    python -m app.seed        (from server/, venv active)

Idempotent — upserts on the natural key, so re-running after adding a row applies just that row.

> **Contract addresses must be verified before a mainnet listing.** The ones below are the
> widely-published values, but "widely-published" is not a control. Confirm each against the
> issuer's own docs and a block explorer before enabling deposits. A wrong address means
> crediting real balances for a worthless token, visible only at reconciliation.
"""

import asyncio
import sys
from decimal import Decimal

from sqlalchemy import select

from app.core.db import AsyncSessionLocal
from app.models import AddressModel, Asset, AssetKind, AssetNetwork, Chain, ChainFamily, Market

# EVM rows differ only in chain id, gas asset and explorer — the whole argument for grouping by
# family: one adapter serves all seven.
CHAINS = [
    dict(code="ETHEREUM", name="Ethereum", family=ChainFamily.EVM, evm_chain_id=1,
         native_asset_symbol="ETH", explorer_tx_url="https://etherscan.io/tx/"),
    dict(code="BSC", name="BNB Smart Chain", family=ChainFamily.EVM, evm_chain_id=56,
         native_asset_symbol="BNB", explorer_tx_url="https://bscscan.com/tx/"),
    dict(code="POLYGON", name="Polygon PoS", family=ChainFamily.EVM, evm_chain_id=137,
         native_asset_symbol="POL", explorer_tx_url="https://polygonscan.com/tx/"),
    dict(code="ARBITRUM", name="Arbitrum One", family=ChainFamily.EVM, evm_chain_id=42161,
         native_asset_symbol="ETH", explorer_tx_url="https://arbiscan.io/tx/"),
    dict(code="OPTIMISM", name="OP Mainnet", family=ChainFamily.EVM, evm_chain_id=10,
         native_asset_symbol="ETH", explorer_tx_url="https://optimistic.etherscan.io/tx/"),
    dict(code="BASE", name="Base", family=ChainFamily.EVM, evm_chain_id=8453,
         native_asset_symbol="ETH", explorer_tx_url="https://basescan.org/tx/"),
    dict(code="AVALANCHE", name="Avalanche C-Chain", family=ChainFamily.EVM, evm_chain_id=43114,
         native_asset_symbol="AVAX", explorer_tx_url="https://snowtrace.io/tx/"),
    dict(code="TRON", name="TRON", family=ChainFamily.TRON, evm_chain_id=None,
         native_asset_symbol="TRX", explorer_tx_url="https://tronscan.org/#/transaction/"),
]

# `scale` must cover the deepest chain an asset lives on. USDT is 6 decimals on Ethereum and TRON
# but **18 on BSC**, so its ledger scale is 18, not the 6 that "USDT has 6 decimals" implies. Set
# it to 6 and every BSC deposit fails or silently rounds the remainder to us — the trigger makes
# that mistake impossible.
ASSETS = [
    dict(symbol="USDT", name="Tether USD", scale=18),
    dict(symbol="USDC", name="USD Coin", scale=6),
    dict(symbol="ETH", name="Ether", scale=18),
    dict(symbol="BNB", name="BNB", scale=18),
    dict(symbol="POL", name="Polygon Ecosystem Token", scale=18),
    dict(symbol="AVAX", name="Avalanche", scale=18),
    dict(symbol="TRX", name="TRON", scale=6),
]

# (asset, chain, contract | None for native, onchain_decimals, confirmations, withdrawal_fee)
# Confirmations and fees are starting points, not researched values — revisit before real
# deposits: too few confirmations is a double-spend window, a fee below network cost is a slow
# drain someone will automate against.
NETWORKS = [
    ("ETH", "ETHEREUM", None, 18, 12, "0.0015"),
    ("ETH", "ARBITRUM", None, 18, 20, "0.0002"),
    ("ETH", "OPTIMISM", None, 18, 20, "0.0002"),
    ("ETH", "BASE", None, 18, 20, "0.0002"),
    ("BNB", "BSC", None, 18, 15, "0.001"),
    ("POL", "POLYGON", None, 18, 128, "0.1"),
    ("AVAX", "AVALANCHE", None, 18, 12, "0.01"),
    ("TRX", "TRON", None, 6, 20, "1"),
    ("USDT", "ETHEREUM", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6, 12, "8"),
    ("USDT", "BSC", "0x55d398326f99059fF775485246999027B3197955", 18, 15, "0.5"),
    ("USDT", "POLYGON", "0xc2132D05D31c914a87C6611C10748AEb04B58e8F", 6, 128, "1"),
    ("USDT", "ARBITRUM", "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9", 6, 20, "1"),
    ("USDT", "TRON", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", 6, 20, "1"),
    ("USDC", "ETHEREUM", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6, 12, "8"),
    ("USDC", "BASE", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, 20, "0.5"),
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        chains: dict[str, Chain] = {}
        for spec in CHAINS:
            existing = (
                await db.execute(select(Chain).where(Chain.code == spec["code"]))
            ).scalar_one_or_none()
            if existing is None:
                existing = Chain(**spec, address_model=AddressModel.PER_USER)
                db.add(existing)
            else:
                for k, v in spec.items():
                    setattr(existing, k, v)
            chains[spec["code"]] = existing
        await db.flush()

        assets: dict[str, Asset] = {}
        for spec in ASSETS:
            existing = (
                await db.execute(select(Asset).where(Asset.symbol == spec["symbol"]))
            ).scalar_one_or_none()
            if existing is None:
                existing = Asset(**spec, kind=AssetKind.CRYPTO)
                db.add(existing)
            else:
                for k, v in spec.items():
                    setattr(existing, k, v)
            assets[spec["symbol"]] = existing
        await db.flush()

        for symbol, chain_code, contract, decimals, confirmations, fee in NETWORKS:
            asset, chain = assets[symbol], chains[chain_code]
            existing = (
                await db.execute(
                    select(AssetNetwork).where(
                        AssetNetwork.asset_id == asset.id, AssetNetwork.chain_id == chain.id
                    )
                )
            ).scalar_one_or_none()
            values = dict(
                contract_address=contract,
                onchain_decimals=decimals,
                confirmations=confirmations,
                confirmations_large=confirmations * 3,
                large_threshold=Decimal("10000"),
                withdrawal_fee=Decimal(fee),
                # Nothing is open for business until custody exists and the contract is verified.
                deposit_enabled=False,
                withdraw_enabled=False,
            )
            if existing is None:
                db.add(AssetNetwork(asset_id=asset.id, chain_id=chain.id, **values))
            else:
                for k, v in values.items():
                    setattr(existing, k, v)

        # --- markets ---------------------------------------------------------------------
        # Pairs we can both price (live Binance data) and fund (USDT quote + a base we support).
        # Symbol -> (base, quote, price_tick, qty_step, min_notional).
        MARKETS = [
            ("ETHUSDT", "ETH", "USDT", "0.01", "0.0001", "5"),
            ("BNBUSDT", "BNB", "USDT", "0.01", "0.001", "5"),
        ]
        for symbol, base, quote, tick, step, min_notional in MARKETS:
            existing = (
                await db.execute(select(Market).where(Market.symbol == symbol))
            ).scalar_one_or_none()
            values = dict(
                base_asset_id=assets[base].id,
                quote_asset_id=assets[quote].id,
                price_tick=Decimal(tick),
                qty_step=Decimal(step),
                min_notional=Decimal(min_notional),
                enabled=True,
            )
            if existing is None:
                db.add(Market(symbol=symbol, **values))
            else:
                for k, v in values.items():
                    setattr(existing, k, v)

        await db.commit()

    print(f"seeded {len(CHAINS)} chains, {len(ASSETS)} assets, {len(NETWORKS)} networks, "
          f"{len(MARKETS)} markets")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed())
