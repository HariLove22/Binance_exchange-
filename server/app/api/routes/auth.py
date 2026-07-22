"""Authentication endpoints: register, login, current-user, and the (disabled) email
verification flow.

Controlled failures use HTTPException — FastAPI turns those into responses *inside* the
middleware stack, so CORS headers survive and the browser can read the status.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.email import send_verification_email
from app.core.security import (
    TokenError,
    create_access_token,
    create_verification_token,
    decode_verification_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email.lower()))


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> RegisterResponse:
    email = body.email.lower()

    if await _get_user_by_email(db, email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    # When verification is disabled, the user is trusted immediately and can log in.
    user = User(
        email=email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        is_verified=not settings.require_email_verification,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Lost the race against a concurrent registration with the same email.
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    await db.refresh(user)

    if settings.require_email_verification:
        send_verification_email(user.email, create_verification_token(user.id))
        return RegisterResponse(
            user=UserOut.model_validate(user),
            requires_verification=True,
            message="Account created. Check your email to verify it, then log in.",
        )

    # No token: registering does not start a session. The user logs in next.
    return RegisterResponse(
        user=UserOut.model_validate(user),
        requires_verification=False,
        message="Account created. Please log in to continue.",
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    user = await _get_user_by_email(db, body.email)

    # Same generic message whether the email is unknown or the password is wrong, so an
    # attacker can't probe which emails are registered.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled")

    if settings.require_email_verification and not user.is_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Please verify your email address before logging in"
        )

    return AuthResponse(
        access_token=create_access_token(user.id), user=UserOut.model_validate(user)
    )


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)) -> UserOut:
    """Return the logged-in user. The client calls this on load to validate a stored token."""
    return UserOut.model_validate(current)


# --- Email verification (wired, but disabled via settings.email_enabled) ----------------

@router.post("/verify-email", response_model=AuthResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    try:
        user_id = decode_verification_token(token)
    except TokenError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired verification link")

    user = await db.get(User, int(user_id))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if not user.is_verified:
        user.is_verified = True
        await db.commit()
        await db.refresh(user)

    # Verified → log them straight in.
    return AuthResponse(
        access_token=create_access_token(user.id), user=UserOut.model_validate(user)
    )


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    body: LoginRequest, db: AsyncSession = Depends(get_db)
) -> MessageResponse:
    # Verify the password so this can't be used to spam arbitrary addresses.
    user = await _get_user_by_email(db, body.email)
    if user and verify_password(body.password, user.password_hash) and not user.is_verified:
        send_verification_email(user.email, create_verification_token(user.id))
    # Always the same reply — don't reveal whether the account exists or is already verified.
    return MessageResponse(message="If the account needs verification, a new link has been sent.")
