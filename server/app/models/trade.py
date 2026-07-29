from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Trade(Base):
    """One execution between exactly two orders.

    A trade is a fact, not a state: it is written once and never updated. Two orders that
    partially fill each other produce one trade for the matched quantity, and both orders
    keep whatever quantity is left.
    """

    __tablename__ = "trades"

    trade_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pair: Mapped[str] = mapped_column(String(20), nullable=False)

    # The MAKER's price — the resting order sets the price, not the incoming one. The taker
    # gets price improvement whenever it was willing to pay more (or accept less).
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)

    taker_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    maker_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.order_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Which side was the aggressor — this is what makes a trade "green" or "red" in a tape.
    taker_side: Mapped[str] = mapped_column(String(4), nullable=False)

    buyer_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    seller_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("price > 0", name="ck_trade_price_positive"),
        CheckConstraint("quantity > 0", name="ck_trade_quantity_positive"),
        CheckConstraint("taker_side IN ('BUY','SELL')", name="ck_trade_taker_side"),
        # An order can never trade with itself.
        CheckConstraint("taker_order_id <> maker_order_id", name="ck_trade_distinct_orders"),
        Index("ix_trades_pair_created", "pair", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Trade {self.trade_id} {self.quantity}@{self.price} taker={self.taker_side}>"
