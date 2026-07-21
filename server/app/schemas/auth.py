import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Server-side password policy — mirrors the client hints, but the server is the real gate
# (a client check can always be bypassed).
_HAS_LOWER = re.compile(r"[a-z]")
_HAS_UPPER = re.compile(r"[A-Z]")
_HAS_DIGIT = re.compile(r"\d")


def _validate_password_strength(pw: str) -> str:
    if len(pw) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not _HAS_LOWER.search(pw):
        raise ValueError("Password must contain a lowercase letter")
    if not _HAS_UPPER.search(pw):
        raise ValueError("Password must contain an uppercase letter")
    if not _HAS_DIGIT.search(pw):
        raise ValueError("Password must contain a number")
    return pw


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    # Max 72 mirrors bcrypt's byte limit (see core/security.py).
    password: str = Field(max_length=72)

    @field_validator("full_name")
    @classmethod
    def _trim_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Please enter your full name")
        return v

    @field_validator("password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    is_verified: bool
    created_at: datetime


class AuthResponse(BaseModel):
    """Returned by both /register and /login.

    access_token is None only when email verification is required and pending — in that case
    the client shows a "check your email" screen instead of logging in.
    """

    access_token: str | None = None
    token_type: str = "bearer"
    requires_verification: bool = False
    user: UserOut


class MessageResponse(BaseModel):
    message: str
