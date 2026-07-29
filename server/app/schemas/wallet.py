from pydantic import BaseModel, Field


class BalanceOut(BaseModel):
    asset: str
    name: str
    # Amounts go out as STRINGS, never JSON numbers: a naive client parses a JSON number
    # into a double and the precision we carefully preserved dies in their parser.
    available: str
    locked: str
    total: str


class BalancesResponse(BaseModel):
    balances: list[BalanceOut]


class FaucetRequest(BaseModel):
    asset: str = Field(min_length=2, max_length=10)
    amount: str = Field(min_length=1, max_length=40)


class FaucetResponse(BaseModel):
    asset: str
    credited: str
    available: str
