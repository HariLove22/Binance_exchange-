from datetime import datetime

from pydantic import BaseModel


class OrderBookEntry(BaseModel):
    order_id: int
    # Amounts go out as STRINGS, never JSON numbers — a naive client parses a JSON number
    # into a double and the precision we preserved dies in their parser. Binance does the same.
    price: str
    quantity: str
    created_at: datetime


class OrderBookResponse(BaseModel):
    pair: str
    bids: list[OrderBookEntry]  # price DESC — best (highest) buyer first
    asks: list[OrderBookEntry]  # price ASC  — best (lowest) seller first
    # Convenience reads off the top of the book; None when that side is empty.
    best_bid: str | None = None
    best_ask: str | None = None
    spread: str | None = None
