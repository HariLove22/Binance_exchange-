"""Token launchpad: create a coin, run an ICO/STO offering, list it on an AMM pool.

A launched token is a **synthetic asset** (Asset.custodial=False) — it lives only as a ledger
balance, never touches a chain, and cannot be withdrawn. Its whole supply is minted to the creator
on launch. It becomes tradeable in two ways, in order:

  1. Offering (ICO/STO) — a fixed-price primary sale that raises USDT. STO adds compliance: only
     whitelisted investors can buy/hold, and tokens are locked until `lockup_until`.
  2. AMM pool — the creator seeds a token/USDT pool; price then floats on the constant-product
     curve (x*y=k) and anyone can swap.

All balances move through the double-entry ledger, so money is conserved (trial balance zero).
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.asset import MONEY, str_enum


class OfferingType(str, enum.Enum):
    ICO = "ICO"   # Initial Coin Offering — utility token, open public sale
    STO = "STO"   # Security Token Offering — regulated: whitelist + lockup + transfer limits


class OfferingStatus(str, enum.Enum):
    DRAFT = "DRAFT"       # created, sale not open yet
    LIVE = "LIVE"         # sale window open
    SUCCESS = "SUCCESS"   # closed at/above soft cap — proceeds released to creator
    FAILED = "FAILED"     # closed below soft cap — buyers refunded
    CLOSED = "CLOSED"     # settled/archived


class LaunchedToken(Base):
    """A user-created coin and its project metadata."""

    __tablename__ = "launched_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), unique=True, nullable=False)
    creator_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    total_supply: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Project fields captured at creation.
    purpose: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    target_audience: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    offering_type: Mapped[OfferingType] = mapped_column(str_enum(OfferingType, "offering_type"), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("total_supply > 0", name="ck_launched_tokens_supply_positive"),
        Index("ix_launched_tokens_creator", "creator_id"),
    )


class TokenOffering(Base):
    """A fixed-price primary sale (ICO or STO) of a launched token, quoted in USDT."""

    __tablename__ = "token_offerings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    offering_type: Mapped[OfferingType] = mapped_column(str_enum(OfferingType, "offering_type"), nullable=False)

    sale_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)        # USDT per token
    tokens_for_sale: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    hard_cap: Mapped[Decimal] = mapped_column(MONEY, nullable=False)          # max USDT to raise
    soft_cap: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    raised: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0), server_default="0")
    tokens_sold: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0), server_default="0")

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[OfferingStatus] = mapped_column(
        str_enum(OfferingStatus, "offering_status"), nullable=False, default=OfferingStatus.DRAFT
    )

    # STO compliance (ignored for ICO).
    requires_whitelist: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    lockup_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "sale_price > 0 AND tokens_for_sale > 0 AND hard_cap > 0 AND soft_cap >= 0 AND soft_cap <= hard_cap",
            name="ck_token_offerings_positive",
        ),
        Index("ix_token_offerings_status", "status"),
    )


class SalePurchase(Base):
    """One buyer's purchase in an offering — used to release tokens on success or refund on failure."""

    __tablename__ = "sale_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("token_offerings.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    usdt_paid: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tokens_bought: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    refunded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_sale_purchases_offering", "offering_id"),)


class InvestorWhitelist(Base):
    """STO only: an investor approved to buy/hold a security token offering."""

    __tablename__ = "investor_whitelist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offering_id: Mapped[int] = mapped_column(ForeignKey("token_offerings.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    __table_args__ = (UniqueConstraint("offering_id", "user_id", name="uq_investor_whitelist"),)


class AmmPool(Base):
    """A constant-product (x*y=k) liquidity pool: a launched token against USDT."""

    __tablename__ = "amm_pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    quote_asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)

    # Cache of the pool's ledger reserves (held in wallet POOL:{id}); a self-check keeps them honest.
    reserve_token: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0), server_default="0")
    reserve_quote: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0), server_default="0")
    fee_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=30)   # 30 = 0.30% to LPs
    lp_supply: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0), server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("token_asset_id", "quote_asset_id", name="uq_amm_pools_pair"),
        CheckConstraint("fee_bps >= 0 AND fee_bps < 10000", name="ck_amm_pools_fee_range"),
    )

    def price(self) -> Decimal | None:
        """Spot price of the token in the quote asset, or None if the pool is empty."""
        return (self.reserve_quote / self.reserve_token) if self.reserve_token > 0 else None


class LpPosition(Base):
    """A liquidity provider's share of a pool."""

    __tablename__ = "lp_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("amm_pools.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    shares: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    __table_args__ = (UniqueConstraint("pool_id", "user_id", name="uq_lp_positions"),)
