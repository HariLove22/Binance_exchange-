import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class UserRole(str, enum.Enum):
    """Two roles, deliberately. The full brief wants a hierarchy (compliance, finance, support…),
    but inventing seats nobody occupies produces permissions nobody has reasoned about. This
    splits the only boundary that exists today: can you see and move other people's money.
    """

    USER = "USER"
    ADMIN = "ADMIN"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Stored lowercased + unique so "A@x.com" and "a@x.com" can't both register.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # bcrypt hash — never the plaintext.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Never settable through any endpoint — registration always produces a USER. An admin is made
    # by an operator running SQL, deliberately. That keeps privilege escalation off the request path.
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=False, length=16,
             values_callable=lambda e: [m.value for m in e]),
        default=UserRole.USER, nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Email-verification flag. While verification is disabled, registration sets this True
    # immediately; when enabled, it stays False until the user clicks the emailed link.
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User id={self.id} email={self.email!r}>"
