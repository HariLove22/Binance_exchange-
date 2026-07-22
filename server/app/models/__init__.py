"""SQLAlchemy models.

Every model module must be imported here. Alembic's autogenerate only sees what is attached to
`Base.metadata` at import time, and a model it cannot see is one it will happily emit a
`DROP TABLE` for. `alembic/env.py` imports this package for exactly that reason.
"""

from app.models.asset import (
    AddressModel,
    Asset,
    AssetKind,
    AssetNetwork,
    Chain,
    ChainFamily,
)
from app.models.ledger import (
    NEGATIVE_ALLOWED,
    USER_ACCOUNT_TYPES,
    Account,
    AccountType,
    LedgerEntry,
    LedgerTransaction,
    TransactionKind,
)
from app.models.user import User, UserRole
from app.models.wallet import (
    Deposit,
    DepositAddress,
    DepositStatus,
    Withdrawal,
    WithdrawalStatus,
)

__all__ = [
    "NEGATIVE_ALLOWED",
    "USER_ACCOUNT_TYPES",
    "Account",
    "AccountType",
    "AddressModel",
    "Asset",
    "AssetKind",
    "AssetNetwork",
    "Chain",
    "ChainFamily",
    "Deposit",
    "DepositAddress",
    "DepositStatus",
    "LedgerEntry",
    "LedgerTransaction",
    "TransactionKind",
    "User",
    "UserRole",
    "Withdrawal",
    "WithdrawalStatus",
]
