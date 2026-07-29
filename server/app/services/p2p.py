"""P2P trading: ads, orders, and the escrow lifecycle.

The exchange is an escrow agent, not a counterparty. The one money rule here: the seller's crypto
is LOCKED the instant an order opens and can leave escrow in exactly two ways — released to the
buyer (seller confirms fiat received) or refunded to the seller (order canceled / dispute lost by
buyer). It is never in two places, and the fiat never touches our books.

Every state transition is authorization-checked (only the right party can drive it) and guarded on
the current status, so the escrow can never be double-released or released after a refund.
"""

from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Asset,
    P2P_OPEN_STATUSES,
    P2PAd,
    P2PAdStatus,
    P2POrder,
    P2POrderStatus,
    P2PSide,
    User,
    UserRole,
)
from app.services import ledger
from app.services.ledger import InsufficientFunds
from app.services.onramp import FIAT_RATES


class P2PError(Exception):
    """A P2P action was refused. Safe to surface to a caller."""


def _q(amount: Decimal, asset: Asset) -> Decimal:
    """Round a crypto amount down to the asset's scale — never hand out more than exists."""
    step = Decimal(1).scaleb(-asset.scale)
    return amount.quantize(step, rounding=ROUND_DOWN)


async def create_ad(
    db: AsyncSession,
    *,
    maker_id: int,
    side: P2PSide,
    asset_id: int,
    fiat: str,
    price: Decimal,
    min_fiat: Decimal,
    max_fiat: Decimal,
    total_qty: Decimal,
    payment_methods: str,
    terms: str | None = None,
) -> P2PAd:
    fiat = fiat.upper()
    if fiat not in FIAT_RATES:
        raise P2PError(f"unsupported fiat {fiat!r}")
    if price <= 0:
        raise P2PError("price must be positive")
    if min_fiat <= 0 or max_fiat < min_fiat:
        raise P2PError("bad order-size limits")
    if total_qty <= 0:
        raise P2PError("total quantity must be positive")
    if not payment_methods.strip():
        raise P2PError("at least one payment method is required")

    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise P2PError("unknown asset")

    ad = P2PAd(
        maker_id=maker_id, side=side, asset_id=asset_id, fiat=fiat, price=price,
        min_fiat=min_fiat, max_fiat=max_fiat, available_qty=_q(total_qty, asset),
        payment_methods=payment_methods.strip(), terms=(terms or None),
        status=P2PAdStatus.ACTIVE,
    )
    db.add(ad)
    await db.flush()
    return ad


async def set_ad_status(db: AsyncSession, *, maker_id: int, ad_id: int, status: P2PAdStatus) -> P2PAd:
    ad = await db.get(P2PAd, ad_id)
    if ad is None or ad.maker_id != maker_id:
        raise P2PError("ad not found")
    ad.status = status
    return ad


async def open_order(
    db: AsyncSession,
    *,
    taker_id: int,
    ad_id: int,
    fiat_amount: Decimal,
    payment_method: str,
) -> P2POrder:
    """A taker fills part of an ad for `fiat_amount` worth of crypto. Locks the seller's escrow."""
    ad = (
        await db.execute(select(P2PAd).where(P2PAd.id == ad_id).with_for_update())
    ).scalar_one_or_none()
    if ad is None:
        raise P2PError("ad not found")
    if ad.status is not P2PAdStatus.ACTIVE:
        raise P2PError("ad is not active")
    if ad.maker_id == taker_id:
        raise P2PError("cannot trade against your own ad")
    if fiat_amount < ad.min_fiat or fiat_amount > ad.max_fiat:
        raise P2PError(f"order must be between {ad.min_fiat} and {ad.max_fiat} {ad.fiat}")
    if payment_method not in {m.strip() for m in ad.payment_methods.split(",")}:
        raise P2PError("payment method not offered on this ad")

    asset = await db.get(Asset, ad.asset_id)
    crypto_amount = _q(fiat_amount / ad.price, asset)
    if crypto_amount <= 0:
        raise P2PError("order too small for this asset's precision")
    if crypto_amount > ad.available_qty:
        raise P2PError("not enough left on this ad")

    # The seller provides crypto, the buyer provides fiat. Which side the taker is on flips with the
    # ad side: a SELL ad has the maker selling, a BUY ad has the taker selling.
    if ad.side is P2PSide.SELL:
        seller_id, buyer_id = ad.maker_id, taker_id
    else:
        seller_id, buyer_id = taker_id, ad.maker_id

    order = P2POrder(
        ad_id=ad.id, maker_id=ad.maker_id, taker_id=taker_id, seller_id=seller_id, buyer_id=buyer_id,
        asset_id=ad.asset_id, fiat=ad.fiat, price=ad.price, crypto_amount=crypto_amount,
        fiat_amount=fiat_amount, payment_method=payment_method, status=P2POrderStatus.PENDING_PAYMENT,
    )
    db.add(order)
    await db.flush()

    # Escrow: lock the seller's crypto. If they don't have it, the order cannot open.
    try:
        await ledger.lock(
            db, user_id=seller_id, asset_id=ad.asset_id, amount=crypto_amount,
            idempotency_key=f"p2p-escrow:{order.id}", reference=f"p2p-order={order.id}",
        )
    except InsufficientFunds as exc:
        raise P2PError(str(exc)) from exc

    ad.available_qty -= crypto_amount
    return order


def _require(order: P2POrder, user_id: int, *, party: str) -> None:
    who = order.buyer_id if party == "buyer" else order.seller_id
    if user_id != who:
        raise P2PError(f"only the {party} can do this")


async def mark_paid(db: AsyncSession, *, user_id: int, order_id: int) -> P2POrder:
    """The buyer declares the fiat sent. PENDING_PAYMENT -> PAID."""
    order = await _locked_order(db, order_id)
    _require(order, user_id, party="buyer")
    if order.status is not P2POrderStatus.PENDING_PAYMENT:
        raise P2PError(f"cannot mark paid from {order.status.value}")
    order.status = P2POrderStatus.PAID
    return order


async def release(db: AsyncSession, *, user_id: int, order_id: int) -> P2POrder:
    """The seller confirms the fiat arrived and releases escrow to the buyer. PAID -> RELEASED."""
    order = await _locked_order(db, order_id)
    _require(order, user_id, party="seller")
    if order.status is not P2POrderStatus.PAID:
        raise P2PError(f"cannot release from {order.status.value} — the buyer must mark paid first")
    await _release_escrow(db, order)
    order.status = P2POrderStatus.RELEASED
    return order


async def cancel(db: AsyncSession, *, user_id: int, order_id: int) -> P2POrder:
    """Drop an unpaid order and refund escrow to the seller. Either party may cancel while unpaid."""
    order = await _locked_order(db, order_id)
    if user_id not in (order.buyer_id, order.seller_id):
        raise P2PError("not your order")
    if order.status is not P2POrderStatus.PENDING_PAYMENT:
        raise P2PError(f"cannot cancel from {order.status.value}")
    await _refund_escrow(db, order)
    order.status = P2POrderStatus.CANCELED
    await _restore_ad_qty(db, order)
    return order


async def open_dispute(db: AsyncSession, *, user_id: int, order_id: int) -> P2POrder:
    """Either party escalates a paid-but-unreleased order to an admin. PAID -> DISPUTED."""
    order = await _locked_order(db, order_id)
    if user_id not in (order.buyer_id, order.seller_id):
        raise P2PError("not your order")
    if order.status is not P2POrderStatus.PAID:
        raise P2PError("only a paid, unreleased order can be disputed")
    order.status = P2POrderStatus.DISPUTED
    return order


async def resolve_dispute(
    db: AsyncSession, *, admin: User, order_id: int, in_favor_of_buyer: bool
) -> P2POrder:
    """An admin settles a dispute: release to the buyer, or refund the seller."""
    if admin.role is not UserRole.ADMIN:
        raise P2PError("only an admin can resolve disputes")
    order = await _locked_order(db, order_id)
    if order.status is not P2POrderStatus.DISPUTED:
        raise P2PError("order is not under dispute")
    if in_favor_of_buyer:
        await _release_escrow(db, order)
        order.status = P2POrderStatus.RELEASED
    else:
        await _refund_escrow(db, order)
        order.status = P2POrderStatus.CANCELED
        await _restore_ad_qty(db, order)
    return order


# --- escrow helpers -------------------------------------------------------------------------------

async def _locked_order(db: AsyncSession, order_id: int) -> P2POrder:
    order = (
        await db.execute(select(P2POrder).where(P2POrder.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None:
        raise P2PError("order not found")
    return order


async def _release_escrow(db: AsyncSession, order: P2POrder) -> None:
    await ledger.p2p_release_escrow(
        db, seller_id=order.seller_id, buyer_id=order.buyer_id, asset_id=order.asset_id,
        amount=order.crypto_amount, idempotency_key=f"p2p-release:{order.id}",
        reference=f"p2p-order={order.id}",
    )


async def _refund_escrow(db: AsyncSession, order: P2POrder) -> None:
    await ledger.unlock(
        db, user_id=order.seller_id, asset_id=order.asset_id, amount=order.crypto_amount,
        idempotency_key=f"p2p-refund:{order.id}", reference=f"p2p-order={order.id}",
    )


async def _restore_ad_qty(db: AsyncSession, order: P2POrder) -> None:
    ad = await db.get(P2PAd, order.ad_id)
    if ad is not None:
        ad.available_qty += order.crypto_amount


# --- reads ----------------------------------------------------------------------------------------

async def browse_ads(
    db: AsyncSession,
    *,
    asset_id: int | None,
    fiat: str | None,
    side: P2PSide | None,
    amount: Decimal | None = None,
    payment_method: str | None = None,
    sort: str = "price",
) -> list[P2PAd]:
    """Active ads, filtered. A taker browsing SELL ads wants to buy; the query mirrors the ad side."""
    q = select(P2PAd).where(P2PAd.status == P2PAdStatus.ACTIVE)
    if asset_id is not None:
        q = q.where(P2PAd.asset_id == asset_id)
    if fiat is not None:
        q = q.where(P2PAd.fiat == fiat.upper())
    if side is not None:
        q = q.where(P2PAd.side == side)
    if amount is not None:
        # Only ads that will accept an order of this fiat size.
        q = q.where(P2PAd.min_fiat <= amount, P2PAd.max_fiat >= amount)
    if payment_method:
        # Comma-joined column, so match the method as a substring token.
        q = q.where(P2PAd.payment_methods.ilike(f"%{payment_method}%"))

    # Best price first for the taker: a SELL ad (taker buys) is best when cheapest; a BUY ad
    # (taker sells) is best when highest.
    if sort == "price":
        if side is P2PSide.SELL:
            q = q.order_by(P2PAd.price.asc())
        elif side is P2PSide.BUY:
            q = q.order_by(P2PAd.price.desc())
        else:
            q = q.order_by(P2PAd.id.desc())
    else:  # "recent"
        q = q.order_by(P2PAd.id.desc())
    return list((await db.execute(q.limit(100))).scalars().all())


async def maker_stats(db: AsyncSession, maker_ids: list[int]) -> dict[int, dict]:
    """Display stats per advertiser: name, completed-order count, and completion rate.

    Completed = RELEASED orders. Completion = released / (released + canceled). A maker with no
    finished orders returns completion None — the UI shows a "New" badge rather than a fake 100%.
    """
    if not maker_ids:
        return {}
    names = dict(
        (await db.execute(select(User.id, User.full_name).where(User.id.in_(maker_ids)))).all()
    )
    rows = (
        await db.execute(
            select(P2POrder.maker_id, P2POrder.status, func.count())
            .where(P2POrder.maker_id.in_(maker_ids))
            .group_by(P2POrder.maker_id, P2POrder.status)
        )
    ).all()
    agg: dict[int, dict] = {}
    for mid, status, cnt in rows:
        a = agg.setdefault(mid, {"released": 0, "finished": 0})
        if status is P2POrderStatus.RELEASED:
            a["released"] += cnt
            a["finished"] += cnt
        elif status is P2POrderStatus.CANCELED:
            a["finished"] += cnt

    out: dict[int, dict] = {}
    for mid in set(maker_ids):
        a = agg.get(mid, {"released": 0, "finished": 0})
        completion = (Decimal(a["released"]) / a["finished"] * 100) if a["finished"] else None
        out[mid] = {"name": names.get(mid) or f"User {mid}", "orders": a["released"], "completion": completion}
    return out


async def my_ads(db: AsyncSession, *, maker_id: int) -> list[P2PAd]:
    """A maker's own ads, active first, newest first — for the My Ads view."""
    q = (
        select(P2PAd)
        .where(P2PAd.maker_id == maker_id, P2PAd.status != P2PAdStatus.CLOSED)
        .order_by(P2PAd.id.desc())
    )
    return list((await db.execute(q.limit(100))).scalars().all())


async def my_orders(db: AsyncSession, *, user_id: int, open_only: bool = False) -> list[P2POrder]:
    q = select(P2POrder).where((P2POrder.taker_id == user_id) | (P2POrder.maker_id == user_id))
    if open_only:
        q = q.where(P2POrder.status.in_(P2P_OPEN_STATUSES))
    return list((await db.execute(q.order_by(P2POrder.id.desc()).limit(100))).scalars().all())


async def list_disputes(db: AsyncSession) -> list[P2POrder]:
    """Every order currently under dispute, oldest first — the admin queue works front to back."""
    return list(
        (
            await db.execute(
                select(P2POrder).where(P2POrder.status == P2POrderStatus.DISPUTED).order_by(P2POrder.id.asc())
            )
        ).scalars().all()
    )
