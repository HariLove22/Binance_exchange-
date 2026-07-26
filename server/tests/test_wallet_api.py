"""Wallet endpoint over HTTP, plus the asset-scale trigger against the real schema.

The API tests hit the app against the test database. `GET /wallet/balances` needs a bearer token,
so these register + log in through Kamni's auth just like a real client.
"""

import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import Asset, AssetKind, Chain, ChainFamily, AddressModel, AssetNetwork

PREFIX = "/api/v1"
PASSWORD = "DemoPass1234"  # satisfies Kamni's policy: upper + lower + digit, 8+


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def register_and_login(client) -> str:
    email = f"wallet-{uuid.uuid4().hex[:12]}@example.com"
    await client.post(f"{PREFIX}/auth/register",
                      json={"email": email, "full_name": "Wallet Tester", "password": PASSWORD})
    res = await client.post(f"{PREFIX}/auth/login", json={"email": email, "password": PASSWORD})
    return res.json()["access_token"]


class TestBalancesEndpoint:
    async def test_requires_auth(self, client):
        assert (await client.get(f"{PREFIX}/wallet/balances")).status_code == 401

    async def test_new_user_has_no_balances(self, client):
        token = await register_and_login(client)
        res = await client.get(f"{PREFIX}/wallet/balances", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        assert res.json() == []


class TestScaleTrigger:
    """The cross-table invariant, against the real migrated schema."""

    async def test_cannot_list_network_deeper_than_asset_scale(self, db):
        chain = Chain(code="TCHAIN", name="T", family=ChainFamily.EVM, evm_chain_id=987654,
                      native_asset_symbol="ETH", address_model=AddressModel.PER_USER, is_testnet=True)
        asset = Asset(symbol="TSCALE", name="T", kind=AssetKind.CRYPTO, scale=8)
        db.add_all([chain, asset])
        await db.flush()
        db.add(AssetNetwork(asset_id=asset.id, chain_id=chain.id, contract_address=None,
                            onchain_decimals=18, confirmations=12, confirmations_large=36,
                            large_threshold=Decimal("10000")))
        with pytest.raises(Exception, match="ledger scale"):
            await db.flush()

    async def test_equal_scale_and_decimals_allowed(self, db):
        chain = Chain(code="TCHAIN2", name="T", family=ChainFamily.EVM, evm_chain_id=987655,
                      native_asset_symbol="ETH", address_model=AddressModel.PER_USER, is_testnet=True)
        asset = Asset(symbol="TSCALE2", name="T", kind=AssetKind.CRYPTO, scale=6)
        db.add_all([chain, asset])
        await db.flush()
        net = AssetNetwork(asset_id=asset.id, chain_id=chain.id, contract_address=None,
                           onchain_decimals=6, confirmations=12, confirmations_large=36,
                           large_threshold=Decimal("10000"))
        db.add(net)
        await db.flush()
        assert net.id is not None
