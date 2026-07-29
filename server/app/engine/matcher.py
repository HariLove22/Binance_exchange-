"""The matching engine.

Deliberately a **pure function**: it takes the incoming order and a snapshot of the opposite
side, and returns the fills. No database, no clock, no randomness, no I/O.

That is not fussiness — it is what makes the engine testable now and replayable later. Anything
non-deterministic in here means the same input can produce a different book, and then a journal
replay (or a hot standby) silently diverges from production.

Two rules do all the work:

1. **Cross check** — a BUY takes any resting ask priced at or below its limit; a SELL takes any
   resting bid priced at or above its limit.
2. **Trade at the MAKER's price** — the resting order set the price. A buyer willing to pay
   50,100 who meets an ask at 50,050 pays 50,050. That difference is price improvement, and
   getting it backwards silently overcharges every taker.

`resting` must already be in price-time priority (best price first, oldest first within a
price). Ordering is the caller's job — see services/orderbook.py.
"""

from dataclasses import dataclass

BUY = "BUY"
SELL = "SELL"


@dataclass(frozen=True)
class RestingOrder:
    order_id: int
    price: int
    remaining: int


@dataclass(frozen=True)
class Fill:
    maker_order_id: int
    price: int  # the maker's price
    quantity: int


def crosses(taker_side: str, taker_price: int, maker_price: int) -> bool:
    if taker_side == BUY:
        return maker_price <= taker_price
    return maker_price >= taker_price


def match(
    taker_side: str,
    taker_price: int,
    taker_quantity: int,
    resting: list[RestingOrder],
) -> tuple[list[Fill], int]:
    """Walk the opposite side and produce fills.

    Returns (fills, remaining) where `remaining` is the taker quantity left unfilled — that is
    what rests on the book afterwards.
    """
    remaining = taker_quantity
    fills: list[Fill] = []

    for maker in resting:
        if remaining <= 0:
            break
        # The book is sorted by price, so the first non-crossing level ends the walk —
        # everything past it is priced even further away.
        if not crosses(taker_side, taker_price, maker.price):
            break
        if maker.remaining <= 0:
            continue

        quantity = min(remaining, maker.remaining)
        fills.append(Fill(maker_order_id=maker.order_id, price=maker.price, quantity=quantity))
        remaining -= quantity

    return fills, remaining
