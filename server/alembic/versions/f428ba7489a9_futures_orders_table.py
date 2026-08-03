"""futures_orders table

Revision ID: f428ba7489a9
Revises: 6db04052bfe4
Create Date: 2026-08-01 20:39:12.210147

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f428ba7489a9'
down_revision: Union[str, None] = '6db04052bfe4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "futures_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.Enum("LONG", "SHORT", name="position_side", native_enum=False, length=32), nullable=False),
        sa.Column("order_type", sa.Enum("LIMIT", "STOP_MARKET", "TAKE_PROFIT", name="futures_order_type", native_enum=False, length=32), nullable=False),
        sa.Column("size", sa.Numeric(precision=36, scale=18), nullable=False),
        sa.Column("price", sa.Numeric(precision=36, scale=18), nullable=False),
        sa.Column("leverage", sa.Numeric(precision=36, scale=18), nullable=False),
        sa.Column("inverse", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("cross", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reduce_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.Enum("PENDING", "FILLED", "CANCELLED", name="futures_order_status", native_enum=False, length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size > 0 AND price > 0 AND leverage >= 1", name="ck_futures_orders_positive"),
    )
    op.create_index("ix_futures_orders_open", "futures_orders", ["status", "symbol"])
    op.create_index("ix_futures_orders_user", "futures_orders", ["user_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_futures_orders_user", table_name="futures_orders")
    op.drop_index("ix_futures_orders_open", table_name="futures_orders")
    op.drop_table("futures_orders")
