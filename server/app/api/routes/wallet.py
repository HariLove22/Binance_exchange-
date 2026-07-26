"""The wallet: balances, deposit addresses, deposits, withdrawals, and reconciliation.

Balances are real from the ledger. Deposits and withdrawals run their full state machines through
a `CustodyProvider` — a mock today (no provider account yet; see docs/03-wallet.md), so the
custody edge is simulated while everything around it is real. The `/dev/*` endpoints stand in for
the chain events a real provider would deliver, and refuse to run outside development.
"""

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.models import Asset, AssetNetwork, Deposit, DepositStatus, User, Withdrawal
from app.services import convert as convert_service
from app.services import deposits as deposit_service
from app.services import ledger
from app.services import onramp as onramp_service
from app.services import reconcile as reconcile_service
from app.services import withdrawals as withdrawal_service
from app.services.convert import ConvertError
from app.services.deposits import DepositError
from app.services.onramp import OnrampError
from app.services.withdrawals import WithdrawalError

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _fmt(value: Decimal, scale: int) -> str:
    return f"{value.quantize(Decimal(1).scaleb(-scale)):f}"


def _require_dev() -> None:
    if settings.environment.lower() not in {"development", "dev", "local", "test"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "dev-only endpoint")


# --- balances -------------------------------------------------------------------------------

class BalanceResponse(BaseModel):
    asset: str
    scale: int
    available: str
    locked: str
    total: str


@router.get("/balances", response_model=list[BalanceResponse])
async def balances(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [
        BalanceResponse(
            asset=b.symbol, scale=b.scale,
            available=_fmt(b.available, b.scale), locked=_fmt(b.locked, b.scale), total=_fmt(b.total, b.scale),
        )
        for b in await ledger.balances(db, user.id)
    ]


# --- networks -------------------------------------------------------------------------------

class NetworkResponse(BaseModel):
    asset_network_id: int
    asset: str
    chain: str
    chain_name: str
    min_withdrawal: str
    withdrawal_fee: str
    confirmations: int
    deposit_enabled: bool
    withdraw_enabled: bool


@router.get("/networks", response_model=list[NetworkResponse])
async def networks(
    asset: str | None = Query(default=None, description="Filter by asset symbol"),
    db: AsyncSession = Depends(get_db),
):
    """The asset-on-chain routes a deposit or withdrawal can target. Public reference data."""
    query = (
        select(AssetNetwork)
        .options(selectinload(AssetNetwork.asset), selectinload(AssetNetwork.chain))
        .join(Asset, Asset.id == AssetNetwork.asset_id)
    )
    if asset:
        query = query.where(Asset.symbol == asset.upper())

    result = []
    for n in (await db.execute(query.order_by(Asset.symbol))).scalars().all():
        result.append(
            NetworkResponse(
                asset_network_id=n.id,
                asset=n.asset.symbol,
                chain=n.chain.code,
                chain_name=n.chain.name,
                min_withdrawal=_fmt(n.min_withdrawal, n.asset.scale),
                withdrawal_fee=_fmt(n.withdrawal_fee, n.asset.scale),
                confirmations=n.confirmations,
                deposit_enabled=n.deposit_enabled,
                withdraw_enabled=n.withdraw_enabled,
            )
        )
    return result


# --- deposits -------------------------------------------------------------------------------

class DepositAddressResponse(BaseModel):
    asset_network_id: int
    address: str
    memo: str | None


@router.post("/deposit/address", response_model=DepositAddressResponse)
async def deposit_address(
    asset_network_id: int = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        addr = await deposit_service.get_or_create_address(db, user.id, asset_network_id)
    except DepositError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return DepositAddressResponse(asset_network_id=asset_network_id, address=addr.address, memo=addr.memo)


class DepositResponse(BaseModel):
    id: int
    asset: str
    chain: str
    tx_hash: str
    amount: str
    status: str
    confirmations: int
    required_confirmations: int


@router.get("/deposits", response_model=list[DepositResponse])
async def deposits(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [DepositResponse(**vars(d)) for d in await deposit_service.list_deposits(db, user.id)]


# --- withdrawals ----------------------------------------------------------------------------

class WithdrawRequest(BaseModel):
    asset_network_id: int
    to_address: str = Field(min_length=4, max_length=128)
    amount: str
    memo: str | None = None
    idempotency_key: str | None = None


class WithdrawalResponse(BaseModel):
    id: int
    asset: str
    chain: str
    to_address: str
    amount: str
    fee: str
    status: str
    tx_hash: str | None


@router.post("/withdraw", response_model=WithdrawalResponse, status_code=status.HTTP_201_CREATED)
async def withdraw(
    body: WithdrawRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request a withdrawal.

    Real withdrawals gate on 2FA, email confirmation and an address whitelist with a time-lock —
    none of which exist on this base yet. This enforces the balance and the state machine; the
    gates are a documented TODO, not a pretence.
    """
    try:
        amount = Decimal(body.amount)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"bad amount {body.amount!r}") from None

    try:
        w = await withdrawal_service.request_withdrawal(
            db,
            user_id=user.id,
            asset_network_id=body.asset_network_id,
            to_address=body.to_address,
            amount=amount,
            memo=body.memo,
            idempotency_key=body.idempotency_key,
        )
    except WithdrawalError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()

    views = {v.id: v for v in await withdrawal_service.list_withdrawals(db, user.id)}
    return WithdrawalResponse(**vars(views[w.id]))


@router.get("/withdrawals", response_model=list[WithdrawalResponse])
async def withdrawals(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return [WithdrawalResponse(**vars(w)) for w in await withdrawal_service.list_withdrawals(db, user.id)]


# --- reconciliation -------------------------------------------------------------------------

class ReconciliationRow(BaseModel):
    asset: str
    trial_balance: str
    ledger_external: str
    custody_onchain: str
    balanced: bool


@router.get("/reconcile", response_model=list[ReconciliationRow])
async def reconcile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Ledger vs custody. Every row must be balanced."""
    return [ReconciliationRow(**vars(r)) for r in await reconcile_service.reconcile(db)]


# --- fiat on-ramp (buy crypto with a currency, converted) -----------------------------------

class CurrencyInfo(BaseModel):
    code: str
    name: str
    per_usd: str


@router.get("/onramp/currencies", response_model=list[CurrencyInfo])
async def onramp_currencies():
    return [
        CurrencyInfo(code=c, name=onramp_service.FIAT_NAMES[c], per_usd=f"{r.normalize():f}")
        for c, r in onramp_service.FIAT_RATES.items()
    ]


class QuoteRequest(BaseModel):
    fiat: str
    fiat_amount: str
    asset: str


class QuoteResponse(BaseModel):
    fiat: str
    fiat_amount: str
    usd_amount: str
    asset: str
    unit_price_usd: str
    crypto_amount: str


def _quote_response(q: onramp_service.Quote) -> QuoteResponse:
    return QuoteResponse(
        fiat=q.fiat, fiat_amount=f"{q.fiat_amount:f}", usd_amount=f"{q.usd_amount:.2f}",
        asset=q.asset, unit_price_usd=f"{q.unit_price_usd:f}", crypto_amount=f"{q.crypto_amount:f}",
    )


@router.post("/onramp/quote", response_model=QuoteResponse)
async def onramp_quote(body: QuoteRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What you'd receive for a fiat amount, at the live price. No funds move."""
    try:
        q = await onramp_service.quote(db, fiat=body.fiat, fiat_amount=Decimal(body.fiat_amount), asset_symbol=body.asset)
    except (OnrampError, InvalidOperation) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _quote_response(q)


@router.post("/onramp/buy", response_model=QuoteResponse, status_code=status.HTTP_201_CREATED)
async def onramp_buy(body: QuoteRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Buy crypto with fiat. Dev only — a mock stand-in for a real payment provider, which would
    charge a card or take a bank transfer before we credit. Credits through the deposit flow so
    the crypto is backed and reconciliation holds."""
    _require_dev()
    try:
        q = await onramp_service.buy(db, user=user, fiat=body.fiat, fiat_amount=Decimal(body.fiat_amount), asset_symbol=body.asset)
    except (OnrampError, InvalidOperation) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _quote_response(q)


# --- convert (instant swap) -----------------------------------------------------------------

class ConvertRequest(BaseModel):
    from_asset: str
    to_asset: str
    from_amount: str


class ConvertResponse(BaseModel):
    from_asset: str
    to_asset: str
    from_amount: str
    to_amount: str
    rate: str


def _convert_response(q: convert_service.ConvertQuote) -> ConvertResponse:
    return ConvertResponse(
        from_asset=q.from_asset, to_asset=q.to_asset,
        from_amount=f"{q.from_amount.normalize():f}", to_amount=f"{q.to_amount.normalize():f}",
        rate=f"{q.rate:f}",
    )


@router.post("/convert/quote", response_model=ConvertResponse)
async def convert_quote(body: ConvertRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """What you'd receive converting one asset to another at the live price. No funds move."""
    try:
        q = await convert_service.quote(db, from_symbol=body.from_asset, to_symbol=body.to_asset,
                                        from_amount=Decimal(body.from_amount))
    except (ConvertError, InvalidOperation) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _convert_response(q)


@router.post("/convert/execute", response_model=ConvertResponse, status_code=status.HTTP_201_CREATED)
async def convert_execute(body: ConvertRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Instantly swap one asset for another at the live price, against the exchange."""
    try:
        q = await convert_service.execute(db, user=user, from_symbol=body.from_asset,
                                          to_symbol=body.to_asset, from_amount=Decimal(body.from_amount))
    except (ConvertError, InvalidOperation) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _convert_response(q)


# --- dev: stand in for chain events ---------------------------------------------------------

@router.post("/dev/enable-networks")
async def dev_enable_networks(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    """Turn on deposits and withdrawals for every network. Dev only.

    The seeder ships them disabled on purpose — nothing accepts *real* funds until custody exists
    and a contract address is verified. In development, against a mock custody provider, enabling
    them is how the flow gets exercised.
    """
    _require_dev()
    from sqlalchemy import update

    result = await db.execute(
        update(AssetNetwork).values(deposit_enabled=True, withdraw_enabled=True)
    )
    await db.commit()
    return {"enabled": result.rowcount or 0}


class SimulateDepositRequest(BaseModel):
    asset_network_id: int
    amount: str
    tx_hash: str | None = None


@router.post("/dev/simulate-deposit", response_model=DepositResponse)
async def simulate_deposit(
    body: SimulateDepositRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Inject an incoming deposit and drive it to CREDITED — what a real chain + custody webhook
    would do. Dev only. The user must already have a deposit address for this network."""
    _require_dev()
    try:
        amount = Decimal(body.amount)
    except InvalidOperation:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad amount") from None

    address = await deposit_service.get_or_create_address(db, user.id, body.asset_network_id)

    import time

    tx_hash = body.tx_hash or f"0xsim{int(time.time() * 1000)}{user.id}"
    try:
        deposit = await deposit_service.record_deposit(
            db,
            asset_network_id=body.asset_network_id,
            tx_hash=tx_hash,
            amount=amount,
        )
    except DepositError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # Attribute to the address owner and fully confirm, then credit — the mock's fast path.
    deposit.user_id = user.id
    deposit.deposit_address_id = address.id
    deposit.confirmations = deposit.required_confirmations
    db.add(deposit)
    await db.flush()
    await deposit_service.credit_if_confirmed(db, deposit)
    await db.commit()

    views = {d.id: d for d in await deposit_service.list_deposits(db, user.id)}
    return DepositResponse(**vars(views[deposit.id]))


@router.post("/dev/withdrawals/{withdrawal_id}/confirm", response_model=WithdrawalResponse)
async def dev_confirm_withdrawal(
    withdrawal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a broadcast withdrawal confirmed — the chain-confirmation event. Dev only."""
    _require_dev()
    w = await db.get(Withdrawal, withdrawal_id)
    if w is None or w.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "withdrawal not found")
    try:
        await withdrawal_service.confirm_withdrawal(db, w)
    except WithdrawalError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    views = {v.id: v for v in await withdrawal_service.list_withdrawals(db, user.id)}
    return WithdrawalResponse(**vars(views[withdrawal_id]))


@router.post("/dev/withdrawals/{withdrawal_id}/fail", response_model=WithdrawalResponse)
async def dev_fail_withdrawal(
    withdrawal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Simulate a failed broadcast — refunds PENDING_WITHDRAWAL to AVAILABLE. Dev only."""
    _require_dev()
    w = await db.get(Withdrawal, withdrawal_id)
    if w is None or w.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "withdrawal not found")
    try:
        await withdrawal_service.fail_withdrawal(db, w, reason="simulated failure")
    except WithdrawalError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    views = {v.id: v for v in await withdrawal_service.list_withdrawals(db, user.id)}
    return WithdrawalResponse(**vars(views[withdrawal_id]))
