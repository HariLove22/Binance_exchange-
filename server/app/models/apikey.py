"""API keys: programmatic access credentials a user creates to drive the exchange from code.

A key has a public identifier and a secret. Only the secret's bcrypt hash is stored — the plaintext
secret is shown exactly once, at creation, and is unrecoverable after. Each key carries granular
permissions (read / trade / withdraw), so a read-only key handed to a dashboard can never move funds.
Revoking sets a flag rather than deleting, keeping an audit trail.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False)

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # public id
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)                  # bcrypt of the secret

    can_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_withdraw: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ApiKey {self.key[:8]}… user={self.user_id}>"
