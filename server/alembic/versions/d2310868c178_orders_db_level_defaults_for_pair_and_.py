"""orders: db-level defaults for pair and status

Revision ID: d2310868c178
Revises: 81dca55a1579
Create Date: 2026-07-23 13:59:12.078924

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2310868c178'
down_revision: Union[str, None] = '81dca55a1579'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defaults applied by Postgres itself, so an insert that omits these columns still lands
    # correctly (the ORM-side default only helps when the ORM does the insert).
    op.alter_column("orders", "pair", server_default="BTC/USDT")
    op.alter_column("orders", "status", server_default="NEW")


def downgrade() -> None:
    op.alter_column("orders", "pair", server_default=None)
    op.alter_column("orders", "status", server_default=None)
