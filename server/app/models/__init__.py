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
    WALLET_FUTURES,
    WALLET_MARGIN,
    WALLET_SPOT,
    Account,
    AccountType,
    LedgerEntry,
    LedgerTransaction,
    TransactionKind,
    isolated_wallet,
)
from app.models.margin import (
    MarginAccount,
    MarginAccountStatus,
    MarginLoan,
    MarginLoanStatus,
    MarginMode,
    MarginTier,
)
from app.models.demo import DemoAccount, DemoHolding
from app.models.kyc import KycApplication, KycStatus
from app.models.futures import FuturesPosition, PositionSide, PositionStatus
from app.models.market import (
    CANCELLABLE_STATUSES,
    Market,
    OPEN_STATUSES,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    STOP_TYPES,
    Trade,
)
from app.models.p2p import (
    P2P_OPEN_STATUSES,
    P2PAd,
    P2PAdStatus,
    P2POrder,
    P2POrderStatus,
    P2PSide,
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
    "WALLET_FUTURES",
    "WALLET_MARGIN",
    "WALLET_SPOT",
    "isolated_wallet",
    "FuturesPosition",
    "PositionSide",
    "PositionStatus",
    "Account",
    "AccountType",
    "AddressModel",
    "Asset",
    "AssetKind",
    "AssetNetwork",
    "Chain",
    "ChainFamily",
    "DemoAccount",
    "DemoHolding",
    "KycApplication",
    "KycStatus",
    "Deposit",
    "DepositAddress",
    "DepositStatus",
    "CANCELLABLE_STATUSES",
    "LedgerEntry",
    "LedgerTransaction",
    "MarginAccount",
    "MarginAccountStatus",
    "MarginLoan",
    "MarginLoanStatus",
    "MarginMode",
    "MarginTier",
    "Market",
    "OPEN_STATUSES",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "P2P_OPEN_STATUSES",
    "P2PAd",
    "P2PAdStatus",
    "P2POrder",
    "P2POrderStatus",
    "P2PSide",
    "STOP_TYPES",
    "Trade",
    "TransactionKind",
    "User",
    "UserRole",
    "Withdrawal",
    "WithdrawalStatus",
]
