"""API key endpoints: create (secret returned once), list, revoke, and a key-authenticated whoami."""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services import apikeys
from app.services.apikeys import ApiKeyError

router = APIRouter(prefix="/apikeys", tags=["apikeys"])


class CreateRequest(BaseModel):
    label: str
    can_trade: bool = False
    can_withdraw: bool = False


class KeyRow(BaseModel):
    id: int
    label: str
    key: str
    can_read: bool
    can_trade: bool
    can_withdraw: bool
    created_at: str
    last_used_at: str | None


class CreatedKey(KeyRow):
    secret: str  # returned exactly once, at creation


def _row(k) -> KeyRow:
    return KeyRow(
        id=k.id, label=k.label, key=k.key, can_read=k.can_read, can_trade=k.can_trade,
        can_withdraw=k.can_withdraw, created_at=k.created_at.isoformat(),
        last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
    )


@router.get("", response_model=list[KeyRow])
async def list_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [_row(k) for k in await apikeys.list_keys(db, user.id)]


@router.post("", response_model=CreatedKey, status_code=status.HTTP_201_CREATED)
async def create_key(body: CreateRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        key, secret = await apikeys.create(db, user=user, label=body.label, can_trade=body.can_trade, can_withdraw=body.can_withdraw)
    except ApiKeyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return CreatedKey(**_row(key).model_dump(), secret=secret)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        await apikeys.revoke(db, user=user, key_id=key_id)
    except ApiKeyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()


class WhoAmI(BaseModel):
    user_id: int
    email: str
    can_read: bool
    can_trade: bool
    can_withdraw: bool


@router.get("/whoami", response_model=WhoAmI)
async def whoami(
    db: AsyncSession = Depends(get_db),
    x_api_key: str | None = Header(default=None),
    x_api_secret: str | None = Header(default=None),
):
    """Authenticate with an API key + secret (headers) instead of a JWT — proves a key works."""
    if not x_api_key or not x_api_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "provide X-API-Key and X-API-Secret headers")
    key = await apikeys.verify(db, key=x_api_key, secret=x_api_secret)
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
    u = await db.get(User, key.user_id)
    return WhoAmI(user_id=key.user_id, email=u.email if u else "?", can_read=key.can_read,
                 can_trade=key.can_trade, can_withdraw=key.can_withdraw)
