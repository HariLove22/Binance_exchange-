"""The custody interface.

Deliberately small. A custody provider does three things the exchange cannot do for itself,
because it is the only thing that holds keys:

- hand out a deposit address for a (user, chain)
- sign and broadcast a withdrawal
- tell us how much it holds on-chain, for reconciliation

Deposits are *not* pulled through this interface — they arrive as events (a provider webhook, or a
node the provider runs) and are fed to the deposit service. That asymmetry mirrors reality: you
ask for an address and a broadcast, but you are *told* about incoming funds.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.models import Chain


@dataclass(frozen=True)
class DerivedAddress:
    address: str
    # Set only for shared-address chains (XRP/TON/XLM), where the memo identifies the user.
    memo: str | None = None


class CustodyProvider(ABC):
    @abstractmethod
    async def derive_address(self, user_id: int, chain: Chain) -> DerivedAddress:
        """A deposit address for this user on this chain.

        For an HD-wallet provider this derives a public child key with no private material online;
        for an API provider it is a call. Either way the private key never reaches this process.
        """

    @abstractmethod
    async def sign_and_broadcast(
        self, *, chain: Chain, to_address: str, amount: Decimal, memo: str | None, reference: str
    ) -> str:
        """Sign a withdrawal and broadcast it. Returns the transaction hash.

        The real signer must independently re-verify destination, amount and limits — trusting the
        caller makes the security boundary the least-patched service. `reference` ties the on-chain
        tx back to our withdrawal record.
        """

    @abstractmethod
    async def on_chain_balance(self, chain: Chain, symbol: str) -> Decimal:
        """What custody reports holding of `symbol` on `chain`, for reconciliation.

        Compared against the ledger's EXTERNAL balance: a mismatch means either a bug in our
        crediting or funds moving that we did not record — both things to halt withdrawals over.
        """
