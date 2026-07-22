"""Assets, chains, and the join between them.

This schema exists to express **"USDT on TRON"** — not an asset and not a chain but the pair,
which carries almost every operational number that matters: contract address, on-chain decimals,
confirmation counts, fees, minimums.

Getting it wrong is expensive in a specific way: a user who deposits USDT on TRON and is credited
against USDT on Ethereum has been handed free money, and reconciliation finds it long after the
withdrawal cleared. Asset and network are never separable.
"""

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# Ledger-tier money: 36 total digits, 18 after the point — enough for an 18-decimal ERC-20 at
# full precision and any supply cap we will list. The matching side uses scaled ints; this type
# never appears on a hot path. Never a float — see app/core/money.py.
MONEY = Numeric(36, 18)


def str_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """A string-backed enum with a CHECK constraint, not a native Postgres ENUM.

    Native PG enums need `ALTER TYPE ... ADD VALUE` to extend — which cannot run in a transaction
    on older servers and can never remove or reorder. We keep adding chain families and account
    types as we go, so a VARCHAR + CHECK, trivially alterable, is the right trade.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ChainFamily(str, enum.Enum):
    """How a chain is talked to, not what it is called.

    Grouping by family is why one adapter serves seven chains: Ethereum, BSC, Polygon, Arbitrum,
    Optimism, Base and Avalanche differ only in chain id and RPC URL — same address format, same
    signing scheme, same JSON-RPC surface.
    """

    EVM = "EVM"
    TRON = "TRON"
    UTXO = "UTXO"  # not built yet; listed so the CHECK need not change later
    SOLANA = "SOLANA"


class AddressModel(str, enum.Enum):
    """How deposits are attributed to a user.

    PER_USER: an address per user; receiving anything at it identifies the owner.
    SHARED_MEMO: ONE address per asset, user identified by a memo / destination tag (XRP, TON,
    XLM). Origin of every "I forgot the memo and my funds are gone" ticket — the watcher must
    reject memo-less transfers rather than guess.
    """

    PER_USER = "PER_USER"
    SHARED_MEMO = "SHARED_MEMO"


class AssetKind(str, enum.Enum):
    CRYPTO = "CRYPTO"
    FIAT = "FIAT"


class Chain(TimestampMixin, Base):
    """A blockchain we can send to and receive from."""

    __tablename__ = "chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Stable machine identifier used in API paths and config: "TRON", "BSC", "ARBITRUM".
    # Not the native symbol — Arbitrum, Optimism and Base all pay gas in ETH.
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    family: Mapped[ChainFamily] = mapped_column(str_enum(ChainFamily, "chain_family"), nullable=False)

    # EIP-155 chain id. Set for EVM chains, NULL otherwise. It is what makes a signed EVM tx
    # non-replayable across chains, so it is not cosmetic: the wrong one makes a mainnet tx valid
    # elsewhere.
    evm_chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Symbol of the asset gas is paid in — the sweeper needs it to answer "can this address
    # afford to move its own tokens".
    native_asset_symbol: Mapped[str] = mapped_column(String(16), nullable=False)

    address_model: Mapped[AddressModel] = mapped_column(
        str_enum(AddressModel, "address_model"), nullable=False, default=AddressModel.PER_USER
    )

    explorer_tx_url: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_testnet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Soft kill switch — disabling stops new deposits/withdrawals without deleting history. An
    # incident-response tool, not config cleanup.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    networks: Mapped[list["AssetNetwork"]] = relationship(back_populates="chain")

    __table_args__ = (
        # EVM without a chain id cannot be signed for; non-EVM with one is a copy-paste error.
        CheckConstraint(
            "(family = 'EVM' AND evm_chain_id IS NOT NULL)"
            " OR (family <> 'EVM' AND evm_chain_id IS NULL)",
            name="ck_chains_evm_chain_id_iff_evm",
        ),
        UniqueConstraint("evm_chain_id", name="uq_chains_evm_chain_id"),
    )

    def __repr__(self) -> str:
        return f"<Chain {self.code}>"


class Asset(TimestampMixin, Base):
    """A unit of value in the ledger — BTC, USDT, INR. Where it lives on-chain is AssetNetwork."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    symbol: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    kind: Mapped[AssetKind] = mapped_column(
        str_enum(AssetKind, "asset_kind"), nullable=False, default=AssetKind.CRYPTO
    )

    # Decimal places the ledger tracks. It must be >= the on-chain decimals of EVERY network this
    # asset lives on, or a deposit arrives with precision the ledger cannot represent and a user's
    # money is silently rounded away. Enforced across the two tables by triggers in the migration.
    scale: Mapped[int] = mapped_column(Integer, nullable=False, default=8)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    networks: Mapped[list["AssetNetwork"]] = relationship(back_populates="asset")

    __table_args__ = (
        CheckConstraint("scale >= 0 AND scale <= 18", name="ck_assets_scale_range"),
    )

    def __repr__(self) -> str:
        return f"<Asset {self.symbol}>"


class AssetNetwork(TimestampMixin, Base):
    """One asset as it exists on one chain — "USDT on TRON".

    Everything operational hangs here rather than on the asset, because the same asset behaves
    differently per chain: USDT costs cents on TRON and dollars on Ethereum, confirms in a minute
    on one and ten on the other, different contract on each.
    """

    __tablename__ = "asset_networks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id", ondelete="RESTRICT"), nullable=False)

    # NULL means the chain's native asset (ETH on Ethereum). Non-NULL is a token contract.
    contract_address: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Decimals as the CHAIN defines them — not necessarily Asset.scale. USDT is 6 on Ethereum and
    # TRON but 18 on BSC. Converting a raw on-chain integer without this number lands deposits
    # 10^n too big or small.
    onchain_decimals: Mapped[int] = mapped_column(Integer, nullable=False)

    # Confirmations before a deposit is credited. Small can credit fast; large should not. One
    # global number is wrong in both directions.
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    confirmations_large: Mapped[int] = mapped_column(Integer, nullable=False, default=32)
    large_threshold: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("10000"))

    min_deposit: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    min_withdrawal: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    # What we charge the user — network cost plus margin, not the floating fee we actually pay.
    withdrawal_fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))

    # Independent switches: halting withdrawals while leaving deposits open (or the reverse) is a
    # standard incident response a single flag cannot express.
    deposit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    withdraw_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    asset: Mapped["Asset"] = relationship(back_populates="networks")
    chain: Mapped["Chain"] = relationship(back_populates="networks")

    __table_args__ = (
        UniqueConstraint("asset_id", "chain_id", name="uq_asset_networks_asset_chain"),
        # One contract is one asset — otherwise the same token listed twice gives a user two
        # balances backed by the same on-chain funds.
        Index(
            "uq_asset_networks_chain_contract",
            "chain_id",
            "contract_address",
            unique=True,
            postgresql_where=contract_address.isnot(None),
        ),
        # A chain has exactly one native asset.
        Index(
            "uq_asset_networks_chain_native",
            "chain_id",
            unique=True,
            postgresql_where=contract_address.is_(None),
        ),
        CheckConstraint("onchain_decimals >= 0 AND onchain_decimals <= 18", name="ck_asset_networks_decimals_range"),
        CheckConstraint(
            "confirmations >= 0 AND confirmations_large >= confirmations",
            name="ck_asset_networks_confirmations_ordered",
        ),
        CheckConstraint(
            "min_deposit >= 0 AND min_withdrawal >= 0 AND withdrawal_fee >= 0",
            name="ck_asset_networks_non_negative_amounts",
        ),
    )

    def __repr__(self) -> str:
        return f"<AssetNetwork asset={self.asset_id} chain={self.chain_id}>"
