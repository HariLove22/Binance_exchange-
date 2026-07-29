"""Demo (paper) trading — a practice sandbox, completely separate from the real ledger.

A demo account holds virtual balances only. Trades fill instantly at the live reference price with no
real counterparty and touch no real money — so it can never affect custody, reconciliation, or the
trial balance. It exists to let users learn the platform risk-free, exactly like Binance's Mock
Trading. Deleting a demo account or resetting its funds has zero effect on anything real.
"""

from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.asset import MONEY, TimestampMixin


class DemoAccount(TimestampMixin, Base):
    """One practice account per user, funded with virtual USDT on creation."""

    __tablename__ = "demo_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    holdings: Mapped[list["DemoHolding"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<DemoAccount user={self.user_id}>"


class DemoHolding(TimestampMixin, Base):
    """A virtual balance of one asset in a demo account. Symbol, not asset_id — demo trades any pair
    priced off the public feed, without needing the asset listed on our real books."""

    __tablename__ = "demo_holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    demo_account_id: Mapped[int] = mapped_column(ForeignKey("demo_accounts.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    account: Mapped["DemoAccount"] = relationship(back_populates="holdings")

    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_demo_holdings_nonneg"),
        UniqueConstraint("demo_account_id", "symbol", name="uq_demo_holdings_account_symbol"),
        Index("ix_demo_holdings_account", "demo_account_id"),
    )

    def __repr__(self) -> str:
        return f"<DemoHolding {self.quantity} {self.symbol}>"
