from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Only one market for now. Kept as a column (not hardcoded in queries) so adding a second
# pair later is a data change, not a schema change.
DEFAULT_PAIR = "BTC/USDT"

# Sides
BUY = "BUY"
SELL = "SELL"

# Statuses — the subset needed before matching exists.
NEW = "NEW"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"
CANCELED = "CANCELED"
REJECTED = "REJECTED"


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # server_default (not just default=) so the value is applied by Postgres too — an insert
    # from a script or psql gets the right pair, not a NOT NULL error.
    pair: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DEFAULT_PAIR, server_default=DEFAULT_PAIR
    )

    side: Mapped[str] = mapped_column(String(4), nullable=False)  # BUY | SELL

    # Scaled integers, never floats — price is in quote units (USDT, scale 8) and quantity in
    # base units (BTC satoshis, scale 8). See app/core/money.py for why.
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # How much of `quantity` has traded. remaining = quantity - filled_quantity.
    # A CANCELED order keeps its filled_quantity — cancelling removes the *rest*, it does not
    # undo what already traded.
    filled_quantity: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NEW, server_default=NEW
    )

    # The "timestamp" column — named created_at to match users/accounts in this schema.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("side IN ('BUY','SELL')", name="ck_order_side"),
        CheckConstraint("price > 0", name="ck_order_price_positive"),
        CheckConstraint("quantity > 0", name="ck_order_quantity_positive"),
        # You can never fill more than was ordered. If this ever trips, the matcher has a bug
        # and the database is the last place that can still stop it.
        CheckConstraint(
            "filled_quantity >= 0 AND filled_quantity <= quantity", name="ck_order_filled_range"
        ),
        # Listing a user's orders, newest first.
        Index("ix_orders_user_created", "user_id", "created_at"),
        # Loading the open book for a pair.
        Index("ix_orders_pair_status", "pair", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<Order {self.order_id} {self.side} {self.quantity}@{self.price} "
            f"{self.pair} {self.status}>"
        )
