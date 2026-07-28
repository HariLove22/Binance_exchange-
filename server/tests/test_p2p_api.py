"""P2P endpoints over HTTP.

These catch a class of bug the service-level tests cannot: route wiring. The order-action routes
forward to the service via a shared helper, and a parameter-name collision there once made every
lifecycle endpoint 500 before the service even ran. A request against a non-existent order exercises
that wiring — it must come back as a clean 400 "not found", never a 500.
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
    email = f"p2p-{uuid.uuid4().hex[:12]}@example.com"
    await client.post(f"{PREFIX}/auth/register",
                      json={"email": email, "full_name": "P2P Tester", "password": PASSWORD})
    res = await client.post(f"{PREFIX}/auth/login", json={"email": email, "password": PASSWORD})
    return res.json()["access_token"]


class TestOrderActionWiring:
    @pytest.mark.parametrize("action", ["paid", "release", "cancel", "dispute"])
    async def test_lifecycle_routes_reach_the_service(self, client, action):
        token = await register_and_login(client)
        # A missing order must surface as a handled 400, proving the route forwarded to the service
        # cleanly (the collision bug made this a 500 before the service ran).
        res = await client.post(f"{PREFIX}/p2p/orders/999999999/{action}",
                                headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 400, res.text
        assert "not found" in res.json()["detail"].lower()

    async def test_lifecycle_requires_auth(self, client):
        assert (await client.post(f"{PREFIX}/p2p/orders/1/paid")).status_code == 401


class TestAdminDisputes:
    async def test_disputes_requires_admin(self, client):
        # A normal user is forbidden; an anonymous caller is unauthorized. Either way, not 200.
        token = await register_and_login(client)
        res = await client.get(f"{PREFIX}/p2p/admin/disputes",
                               headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 403
        assert (await client.get(f"{PREFIX}/p2p/admin/disputes")).status_code == 401


class TestBrowseAdsPublic:
    async def test_browse_is_public_and_shaped(self, client):
        res = await client.get(f"{PREFIX}/p2p/ads")
        assert res.status_code == 200
        assert isinstance(res.json(), list)
