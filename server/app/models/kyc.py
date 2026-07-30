"""KYC (Know Your Customer) identity verification.

One application per user. A user submits identity details, which sit in PENDING until an operator
approves or rejects them — the same review pattern as P2P disputes. There is no real identity
provider wired in, so this is the record and workflow; a production system would forward the details
(and document images) to a KYC vendor and reconcile the result here. Approval unlocks higher limits
in a real deployment; here it is tracked but not yet enforced.
"""

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import TimestampMixin, str_enum


class KycStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"  # never used as a stored value; the absence of a row means this
    PENDING = "PENDING"          # submitted, awaiting review
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"        # rejected; the user may correct and resubmit


class KycApplication(TimestampMixin, Base):
    """A user's identity submission and its review state. One row per user (resubmit updates it)."""

    __tablename__ = "kyc_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    status: Mapped[KycStatus] = mapped_column(
        str_enum(KycStatus, "kyc_status"), nullable=False, default=KycStatus.PENDING
    )

    legal_name: Mapped[str] = mapped_column(String(120), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    country: Mapped[str] = mapped_column(String(56), nullable=False)
    id_type: Mapped[str] = mapped_column(String(32), nullable=False)   # PASSPORT / NATIONAL_ID / DRIVERS_LICENSE
    id_number: Mapped[str] = mapped_column(String(64), nullable=False)

    # Uploaded documents, stored as base64 data URIs (client downscales before upload). Front of the
    # ID is required; the back and a selfie are optional. Kept out of list/status responses — only
    # the admin detail view returns them, so the heavy blobs never travel unnecessarily.
    doc_front: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_back: Mapped[str | None] = mapped_column(Text, nullable=True)
    selfie: Mapped[str | None] = mapped_column(Text, nullable=True)

    reject_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<KycApplication user={self.user_id} {self.status.value}>"
