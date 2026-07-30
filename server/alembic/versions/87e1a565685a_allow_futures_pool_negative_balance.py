"""allow futures_pool negative balance

Revision ID: 87e1a565685a
Revises: 4eebb056dc63
Create Date: 2026-07-30 15:36:50.907653

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '87e1a565685a'
down_revision: Union[str, None] = '4eebb056dc63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NAME = "ck_accounts_no_negative_user_balance"
_WITH = "balance >= 0 OR account_type IN ('EXTERNAL', 'TDS_PAYABLE', 'MARGIN_BORROWED', 'FUTURES_POOL')"
_WITHOUT = "balance >= 0 OR account_type IN ('EXTERNAL', 'TDS_PAYABLE', 'MARGIN_BORROWED')"


def upgrade() -> None:
    op.drop_constraint(_NAME, "accounts", type_="check")
    op.create_check_constraint(_NAME, "accounts", _WITH)


def downgrade() -> None:
    op.drop_constraint(_NAME, "accounts", type_="check")
    op.create_check_constraint(_NAME, "accounts", _WITHOUT)
