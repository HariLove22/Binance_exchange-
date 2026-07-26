"""Shared route dependencies.

`get_current_user` is the gate for protected endpoints: it pulls the Bearer token, verifies
it, and loads the user — or raises 401. HTTPException (not a bare raise) is correct here:
FastAPI handles it *inside* the middleware stack, so CORSMiddleware still adds its headers and
the browser can read the 401. (The README's "return, never raise" rule is about *unhandled*
500s, which bypass CORS — not controlled HTTPExceptions.)
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import TokenError, decode_access_token
from app.models.user import User, UserRole

_bearer = HTTPBearer(auto_error=False)
_WWW_AUTH = {"WWW-Authenticate": "Bearer"}


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers=_WWW_AUTH)

    try:
        user_id = decode_access_token(creds.credentials)
    except TokenError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers=_WWW_AUTH
        )

    user = await db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists", headers=_WWW_AUTH)

    return user


async def admin_user(user: User = Depends(get_current_user)) -> User:
    """Gate for admin-only routes. 403, not 404: the routes are in the public OpenAPI schema
    anyway, and a wrong status makes a real permission problem look like a typo during an incident.

    Role is never settable through any endpoint — an admin is made by an operator running SQL, so
    privilege escalation stays entirely off the request path.
    """
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return user
