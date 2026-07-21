"""Password hashing and JWT tokens.

Two independent jobs:

- **Hashing** — turn a password into an irreversible bcrypt hash for storage, and verify a
  candidate against a stored hash. Plaintext is never stored or logged.
- **Tokens** — mint a short-lived JWT after login, and decode/verify one on a protected
  request. The token is *signed* (not encrypted): the payload is readable but tamper-proof,
  so we trust the user id inside it without a database lookup. Verification-email links use a
  separate token "purpose" so the two can never be swapped.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# bcrypt silently truncates input past 72 bytes, which would make two different long
# passwords collide. Reject early instead.
_MAX_PASSWORD_BYTES = 72

_ACCESS = "access"
_VERIFY = "email_verify"


class TokenError(Exception):
    """Raised when a JWT is missing, expired, malformed, or fails signature/purpose checks."""


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > _MAX_PASSWORD_BYTES:
        raise ValueError("password too long (max 72 bytes)")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    pw = password.encode("utf-8")
    if len(pw) > _MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except ValueError:
        return False  # malformed stored hash → treat as non-match, don't crash


def _create_token(subject: str | int, purpose: str, expires_in: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(subject), "purpose": purpose, "iat": now, "exp": now + expires_in}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, expected_purpose: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("purpose") != expected_purpose:
        raise TokenError("token has the wrong purpose")
    sub = payload.get("sub")
    if not sub:
        raise TokenError("token missing subject")
    return sub


def create_access_token(subject: str | int) -> str:
    return _create_token(subject, _ACCESS, timedelta(minutes=settings.access_token_expire_minutes))


def decode_access_token(token: str) -> str:
    return _decode_token(token, _ACCESS)


def create_verification_token(subject: str | int) -> str:
    return _create_token(subject, _VERIFY, timedelta(hours=settings.verification_token_expire_hours))


def decode_verification_token(token: str) -> str:
    return _decode_token(token, _VERIFY)
