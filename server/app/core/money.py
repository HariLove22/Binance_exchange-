"""Money handling. Read this before touching any balance, price, or quantity.

The rule: **money is never a float**. Not in the engine, not in the ledger, not on the wire.

`0.1 + 0.2 != 0.3` in IEEE 754. A float64 carries a 53-bit mantissa, ~15.95 decimal digits.
The 21M BTC supply in satoshis needs 2.1e15 — that sits right at the edge, and any intermediate
multiply (price x quantity) blows straight past it. Wei (1e18) is hopeless from the start.

Two representations, two jobs:

- `Decimal` at the API and ledger edge. Correct, readable, slow. Fine here.
- scaled `int` in the engine. The asset's minimum unit (satoshis for BTC, ticks for price).
  All engine math is integer add/sub/compare. Python ints are arbitrary-precision, so the
  i128-overflow concern from C++/Rust engines does not apply — but the discipline does.

Rounding is a business decision, never a default. Every rounding is explicit and consistent,
and rounds in the conservative direction. When splitting an amount across parties, allocate the
remainder deterministically to one party — rounding each leg independently creates or destroys
dust, and the ledger's trial balance will catch you.

On the wire, quantities go out as **strings**, never JSON numbers. Binance does this for the
same reason: a JSON number gets parsed into a double by a naive client, and the precision you
carefully preserved dies in someone else's parser.
"""

from decimal import Decimal, InvalidOperation, localcontext

# Scale = number of decimal places tracked internally, per asset class.
# BTC -> 8 (satoshi). Most fiat -> 2. We keep a generous default and pin per-asset later,
# once the `assets` table exists.
DEFAULT_SCALE = 8
PRICE_SCALE = 8


class MoneyError(ValueError):
    """Raised when a value cannot be represented exactly as money."""


def to_decimal(value: str | int | Decimal) -> Decimal:
    """Parse a money value. Rejects floats loudly rather than silently losing precision."""
    if isinstance(value, float):
        raise MoneyError(
            "float is not accepted as money — pass a str, int, or Decimal. "
            "See the module docstring for why."
        )
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise MoneyError(f"not a valid money value: {value!r}") from exc


def to_scaled_int(value: str | int | Decimal, scale: int = DEFAULT_SCALE) -> int:
    """Convert a decimal amount to the integer count of its minimum unit.

    `to_scaled_int("1.5", scale=8) -> 150_000_000`

    Raises if the value carries more precision than the scale allows, rather than rounding
    silently. An order for 0.000000001 BTC is a bug in the caller, not something to round away.
    """
    dec = to_decimal(value)
    with localcontext() as ctx:
        ctx.prec = 60
        shifted = dec.scaleb(scale)
        if shifted != shifted.to_integral_value():
            raise MoneyError(
                f"{dec} carries more precision than scale {scale} allows"
            )
        return int(shifted)


def from_scaled_int(value: int, scale: int = DEFAULT_SCALE) -> Decimal:
    """Inverse of `to_scaled_int`. `from_scaled_int(150_000_000, 8) -> Decimal("1.5")`"""
    with localcontext() as ctx:
        ctx.prec = 60
        return Decimal(value).scaleb(-scale)


def format_money(value: Decimal, scale: int = DEFAULT_SCALE) -> str:
    """Render for the wire: fixed scale, always a string, never scientific notation.

    `format_money(Decimal("1.5"), 8) -> "1.50000000"`
    """
    with localcontext() as ctx:
        ctx.prec = 60
        quantized = value.quantize(Decimal(1).scaleb(-scale))
        return f"{quantized:f}"
