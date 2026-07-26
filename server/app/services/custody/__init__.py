"""Custody — the external half of the wallet, behind one interface.

Everything the rest of the code needs from a custody provider goes through `CustodyProvider`. The
deposit and withdrawal services never import a concrete provider; they take the interface. Swapping
the mock for Fireblocks / BitGo / Turnkey later is one line here, not a hunt through the codebase.

`custody` is the process-wide instance. It is the mock today because there is no provider account
(see docs/03-wallet.md); it will become the real one when there is.
"""

from app.services.custody.base import CustodyProvider, DerivedAddress
from app.services.custody.mock import MockCustodyProvider

custody: CustodyProvider = MockCustodyProvider()

__all__ = ["CustodyProvider", "DerivedAddress", "MockCustodyProvider", "custody"]
