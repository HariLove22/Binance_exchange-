"""futures cross margin flag

Revision ID: 6db04052bfe4
Revises: bb10f3ea66bc
Create Date: 2026-08-01 20:09:01.617920

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6db04052bfe4'
down_revision: Union[str, None] = 'bb10f3ea66bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('futures_positions', sa.Column('cross', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('futures_positions', 'cross')
