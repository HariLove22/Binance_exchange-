"""merge futures and referral/rewards

Revision ID: 07145424c429
Revises: 87e1a565685a, 9f44fd266294
Create Date: 2026-07-30 17:08:58.696579

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07145424c429'
down_revision: Union[str, None] = ('87e1a565685a', '9f44fd266294')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
