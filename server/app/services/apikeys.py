"""API key service: create (secret shown once), list, revoke, and verify.

The secret is generated, its bcrypt hash stored, and the plaintext returned only from `create`. A key
carries read / trade / withdraw permissions so a limited key can be handed out safely. `verify` is
the gate an API-key-authenticated request goes through.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models import ApiKey, User

MAX_KEYS = 10


class ApiKeyError(Exception):
    """An API-key action was refused. Safe to surface to a caller."""


async def create(db: AsyncSession, *, user: User, label: str, can_trade: bool, can_withdraw: bool) -> tuple[ApiKey, str]:
    label = label.strip()
    if len(label) < 2:
        raise ApiKeyError("give the key a name")
    active = (await db.execute(
        select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.revoked.is_(False))
    )).scalars().all()
    if len(active) >= MAX_KEYS:
        raise ApiKeyError(f"you can have at most {MAX_KEYS} active keys")

    key = secrets.token_hex(16)          # public identifier
    plaintext_secret = secrets.token_urlsafe(32)
    api_key = ApiKey(
        user_id=user.id, label=label, key=key, secret_hash=hash_password(plaintext_secret),
        can_read=True, can_trade=can_trade, can_withdraw=can_withdraw,
    )
    db.add(api_key)
    await db.flush()
    return api_key, plaintext_secret


async def list_keys(db: AsyncSession, user_id: int) -> list[ApiKey]:
    return list((await db.execute(
        select(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked.is_(False)).order_by(ApiKey.id.desc())
    )).scalars().all())


async def revoke(db: AsyncSession, *, user: User, key_id: int) -> None:
    api_key = await db.get(ApiKey, key_id)
    if api_key is None or api_key.user_id != user.id:
        raise ApiKeyError("key not found")
    api_key.revoked = True


async def verify(db: AsyncSession, *, key: str, secret: str) -> ApiKey | None:
    """Return the live key if the public id + secret match and it isn't revoked, else None."""
    api_key = (await db.execute(select(ApiKey).where(ApiKey.key == key, ApiKey.revoked.is_(False)))).scalar_one_or_none()
    if api_key is None or not verify_password(secret, api_key.secret_hash):
        return None
    return api_key
