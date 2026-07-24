from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.order import DEFAULT_PAIR


class PlaceOrderRequest(BaseModel):
    side: Literal["BUY", "SELL"]
    # Decimal strings, not floats — the same discipline the responses use. "50050.00", "1.5".
    price: str = Field(min_length=1, max_length=40)
    quantity: str = Field(min_length=1, max_length=40)
    pair: str = DEFAULT_PAIR


class FillOut(BaseModel):
    """One execution against a resting order. `price` is the maker's price."""

    maker_order_id: int
    price: str
    quantity: str


class OrderOut(BaseModel):
    order_id: int
    pair: str
    side: str
    price: str
    quantity: str
    filled_quantity: str
    status: str
    created_at: datetime
    # The full execution report is returned synchronously so the client never has to read
    # back what it just wrote (no read-after-write 404s). Binance does the same.
    fills: list[FillOut] = []
