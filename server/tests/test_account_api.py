"""Account self-service: profile edit and password change over HTTP."""

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


async def register(client) -> tuple[str, str]:
    email = f"acct-{uuid.uuid4().hex[:12]}@example.com"
    res = await client.post(f"{PREFIX}/auth/register",
                            json={"email": email, "full_name": "Acct Tester", "password": PASSWORD})
    return email, res.json()["access_token"]


class TestProfile:
    async def test_update_name(self, client):
        _, token = await register(client)
        h = {"Authorization": f"Bearer {token}"}
        res = await client.patch(f"{PREFIX}/auth/profile", headers=h, json={"full_name": "New Name"})
        assert res.status_code == 200
        assert res.json()["full_name"] == "New Name"
        assert (await client.get(f"{PREFIX}/auth/me", headers=h)).json()["full_name"] == "New Name"

    async def test_short_name_rejected(self, client):
        _, token = await register(client)
        res = await client.patch(f"{PREFIX}/auth/profile",
                                 headers={"Authorization": f"Bearer {token}"}, json={"full_name": "x"})
        assert res.status_code == 422


class TestPassword:
    async def test_change_and_relogin(self, client):
        email, token = await register(client)
        h = {"Authorization": f"Bearer {token}"}
        new_pw = "BrandNew1234"

        # Wrong current password is refused.
        bad = await client.post(f"{PREFIX}/auth/change-password", headers=h,
                                json={"current_password": "wrongpass1A", "new_password": new_pw})
        assert bad.status_code == 400

        # Correct change succeeds.
        ok = await client.post(f"{PREFIX}/auth/change-password", headers=h,
                               json={"current_password": PASSWORD, "new_password": new_pw})
        assert ok.status_code == 200

        # Old password no longer logs in; new one does.
        assert (await client.post(f"{PREFIX}/auth/login",
                                  json={"email": email, "password": PASSWORD})).status_code == 401
        relog = await client.post(f"{PREFIX}/auth/login", json={"email": email, "password": new_pw})
        assert relog.status_code == 200 and relog.json()["access_token"]

    async def test_weak_new_password_rejected(self, client):
        _, token = await register(client)
        res = await client.post(f"{PREFIX}/auth/change-password",
                                headers={"Authorization": f"Bearer {token}"},
                                json={"current_password": PASSWORD, "new_password": "weak"})
        assert res.status_code == 422

    async def test_requires_auth(self, client):
        assert (await client.post(f"{PREFIX}/auth/change-password",
                                  json={"current_password": "x", "new_password": "Whatever123"})).status_code == 401
