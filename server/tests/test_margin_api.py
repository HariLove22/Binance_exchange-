"""Margin endpoints over HTTP — wiring and gating.

A fresh margin account holds nothing, so opening and reading it needs no price lookup and stays
offline. That is enough to prove the routes reach the service and shape their responses.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PREFIX = "/api/v1"
PASSWORD = "DemoPass1234"


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def register_and_login(client) -> str:
    email = f"mgn-{uuid.uuid4().hex[:12]}@example.com"
    await client.post(f"{PREFIX}/auth/register",
                      json={"email": email, "full_name": "Margin Tester", "password": PASSWORD})
    res = await client.post(f"{PREFIX}/auth/login", json={"email": email, "password": PASSWORD})
    return res.json()["access_token"]


class TestAccountLifecycle:
    async def test_open_and_read(self, client):
        token = await register_and_login(client)
        h = {"Authorization": f"Bearer {token}"}

        # No account yet.
        assert (await client.get(f"{PREFIX}/margin/account", headers=h)).status_code == 404

        # Open a cross Pro account at 5x.
        res = await client.post(f"{PREFIX}/margin/account", headers=h,
                                json={"mode": "CROSS", "tier": "PRO", "leverage": "5"})
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["mode"] == "CROSS"
        assert body["max_leverage"] == "5"
        assert body["health"] == "safe"
        assert body["margin_level"] is None
        assert body["loans"] == []

        # Now it reads back.
        assert (await client.get(f"{PREFIX}/margin/account", headers=h)).status_code == 200

    async def test_leverage_over_tier_cap_rejected(self, client):
        token = await register_and_login(client)
        h = {"Authorization": f"Bearer {token}"}
        res = await client.post(f"{PREFIX}/margin/account", headers=h,
                                json={"mode": "CROSS", "tier": "CLASSIC", "leverage": "10"})
        assert res.status_code == 400
        assert "3x" in res.json()["detail"]

    async def test_requires_auth(self, client):
        assert (await client.get(f"{PREFIX}/margin/account")).status_code == 401
        assert (await client.post(f"{PREFIX}/margin/account", json={})).status_code == 401
