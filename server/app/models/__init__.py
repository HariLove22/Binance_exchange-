"""SQLAlchemy models. Importing them here registers every table on Base.metadata so
Alembic autogenerate and create_all see the full schema from one place.
"""

from app.models.user import User
from app.models.wallet import Account, LedgerEntry, Transaction

__all__ = ["User", "Account", "Transaction", "LedgerEntry"]
