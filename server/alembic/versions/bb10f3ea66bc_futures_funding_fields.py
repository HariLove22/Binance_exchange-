"""futures funding fields

Revision ID: bb10f3ea66bc
Revises: a969c318ef6d
Create Date: 2026-08-01 15:08:51.491115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'bb10f3ea66bc'
down_revision: Union[str, None] = 'a969c318ef6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('futures_positions', sa.Column('last_funding_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('futures_positions', sa.Column('funding_accrued', sa.Numeric(precision=36, scale=18), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('futures_positions', 'funding_accrued')
    op.drop_column('futures_positions', 'last_funding_at')
