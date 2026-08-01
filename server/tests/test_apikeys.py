"""API keys: create (secret once), permissions, verify, revoke."""

import pytest

from app.services import apikeys
from tests.test_trading import make_user


class TestApiKeys:
    async def test_create_and_verify(self, db):
        u = await make_user(db, "ak-create@example.com")
        key, secret = await apikeys.create(db, user=u, label="Bot", can_trade=True, can_withdraw=False)
        assert key.can_read is True and key.can_trade is True and key.can_withdraw is False
        # Correct secret verifies; wrong one doesn't.
        assert (await apikeys.verify(db, key=key.key, secret=secret)) is not None
        assert (await apikeys.verify(db, key=key.key, secret="wrong")) is None

    async def test_list_excludes_revoked(self, db):
        u = await make_user(db, "ak-list@example.com")
        k1, _ = await apikeys.create(db, user=u, label="Key A", can_trade=False, can_withdraw=False)
        await apikeys.create(db, user=u, label="Key B", can_trade=False, can_withdraw=False)
        assert len(await apikeys.list_keys(db, u.id)) == 2
        await apikeys.revoke(db, user=u, key_id=k1.id)
        keys = await apikeys.list_keys(db, u.id)
        assert len(keys) == 1 and keys[0].label == "Key B"

    async def test_revoked_key_fails_verify(self, db):
        u = await make_user(db, "ak-revoke@example.com")
        key, secret = await apikeys.create(db, user=u, label="Key X", can_trade=False, can_withdraw=False)
        await apikeys.revoke(db, user=u, key_id=key.id)
        assert (await apikeys.verify(db, key=key.key, secret=secret)) is None

    async def test_cannot_revoke_others_key(self, db):
        u1 = await make_user(db, "ak-a@example.com")
        u2 = await make_user(db, "ak-b@example.com")
        key, _ = await apikeys.create(db, user=u1, label="Key A", can_trade=False, can_withdraw=False)
        with pytest.raises(apikeys.ApiKeyError, match="not found"):
            await apikeys.revoke(db, user=u2, key_id=key.id)

    async def test_label_required(self, db):
        u = await make_user(db, "ak-label@example.com")
        with pytest.raises(apikeys.ApiKeyError, match="name"):
            await apikeys.create(db, user=u, label="", can_trade=False, can_withdraw=False)
