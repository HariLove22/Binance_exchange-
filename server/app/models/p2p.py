"""Peer-to-peer trading: fiat <-> crypto between users, with the exchange as escrow only.

This is NOT the matching engine. There is no order book and no price discovery here. A maker posts
an **ad** ("I'll sell USDT at ₹90 via UPI"); a taker opens an **order** against it. The fiat moves
directly between the two people, off-platform (UPI, bank transfer). The exchange's only job is to
hold the crypto in escrow so neither side can cheat: the seller's crypto is LOCKED the moment an
order opens, and released to the buyer only once the seller confirms the fiat arrived.

Escrow reuses the ledger's lock/unlock (AVAILABLE <-> LOCKED) plus one release that moves the
locked crypto to the buyer. No money is created — the crypto is real and on our books; only the
fiat is external, which is exactly why we never touch it.
"""

import enum
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import MONEY, TimestampMixin, str_enum


class P2PSide(str, enum.Enum):
    """The side is from the ad MAKER's point of view, like Binance.

    BUY  — the maker wants to buy crypto; the taker is the seller (taker's crypto is escrowed).
    SELL — the maker wants to sell crypto; the taker is the buyer (maker's crypto is escrowed).
    """

    BUY = "BUY"
    SELL = "SELL"


class P2PAdStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"    # visible and open for orders
    PAUSED = "PAUSED"    # hidden, kept for reuse
    CLOSED = "CLOSED"    # retired


class P2POrderStatus(str, enum.Enum):
    """Lifecycle of one P2P order.

    PENDING_PAYMENT — crypto escrowed; the buyer must now pay fiat off-platform.
    PAID            — the buyer says they paid; the seller should verify and release.
    RELEASED        — the seller released escrow to the buyer. Terminal, successful.
    CANCELED        — dropped before payment; escrow refunded to the seller. Terminal.
    DISPUTED        — buyer paid but seller won't release (or vice versa); an admin decides.
    """

    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    RELEASED = "RELEASED"
    CANCELED = "CANCELED"
    DISPUTED = "DISPUTED"


# An order is live (escrow held, still moving) in these states; terminal otherwise.
P2P_OPEN_STATUSES = frozenset({P2POrderStatus.PENDING_PAYMENT, P2POrderStatus.PAID, P2POrderStatus.DISPUTED})


class P2PAd(TimestampMixin, Base):
    """A standing offer to buy or sell a crypto for a fiat currency at a fixed price."""

    __tablename__ = "p2p_ads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    maker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    side: Mapped[P2PSide] = mapped_column(str_enum(P2PSide, "p2p_side"), nullable=False)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    fiat: Mapped[str] = mapped_column(String(8), nullable=False)  # e.g. INR, USD

    # Fiat per one unit of crypto. Fiat order-size band, so an ad can serve many small takers.
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    min_fiat: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_fiat: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    # How much crypto is still available across all future orders on this ad. Decremented as orders
    # open, restored if they cancel. When it can no longer cover min_fiat, the ad is effectively done.
    available_qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    # Comma-separated payment rails the maker accepts, e.g. "UPI,IMPS,BANK". Free-form terms note.
    payment_methods: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    terms: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[P2PAdStatus] = mapped_column(
        str_enum(P2PAdStatus, "p2p_ad_status"), nullable=False, default=P2PAdStatus.ACTIVE
    )

    __table_args__ = (
        CheckConstraint("price > 0", name="ck_p2p_ads_price_positive"),
        CheckConstraint("min_fiat > 0 AND max_fiat >= min_fiat", name="ck_p2p_ads_limits"),
        CheckConstraint("available_qty >= 0", name="ck_p2p_ads_qty_nonneg"),
        Index("ix_p2p_ads_browse", "asset_id", "fiat", "side", "status"),
        Index("ix_p2p_ads_maker", "maker_id"),
    )

    def __repr__(self) -> str:
        return f"<P2PAd {self.side.value} {self.available_qty} @ {self.price} {self.fiat}>"


class P2POrder(TimestampMixin, Base):
    """One taker filling part of an ad. Escrow is held against `seller_id` while it is live."""

    __tablename__ = "p2p_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("p2p_ads.id", ondelete="RESTRICT"), nullable=False)

    maker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    taker_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # Who provides what. Derived from the ad's side at open time and then fixed, so the escrow and
    # release logic never has to re-derive it: escrow always locks the SELLER's crypto.
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    fiat: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    crypto_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # escrowed
    fiat_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)    # paid off-platform
    payment_method: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[P2POrderStatus] = mapped_column(
        str_enum(P2POrderStatus, "p2p_order_status"), nullable=False, default=P2POrderStatus.PENDING_PAYMENT
    )

    __table_args__ = (
        CheckConstraint("crypto_amount > 0 AND fiat_amount > 0 AND price > 0", name="ck_p2p_orders_positive"),
        CheckConstraint("seller_id <> buyer_id", name="ck_p2p_orders_distinct_parties"),
        Index("ix_p2p_orders_ad", "ad_id"),
        Index("ix_p2p_orders_taker", "taker_id", "id"),
        Index("ix_p2p_orders_maker", "maker_id", "id"),
    )

    def __repr__(self) -> str:
        return f"<P2POrder {self.id} {self.status.value} {self.crypto_amount} for {self.fiat_amount} {self.fiat}>"
