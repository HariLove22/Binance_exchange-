"""A tiny in-process publish/subscribe bus for live market updates.

When an order is placed, cancelled or filled, the trade layer publishes a signal on the symbol's
channel; WebSocket connections subscribed to that symbol wake up and push a fresh book and trades.
No client polling, and updates are instant on activity rather than on a timer.

In-process is the right scope for now: a single API worker. It is deliberately behind a thin
interface (`publish` / `subscribe`) so moving to Redis pub/sub for multiple workers later is one
adapter, not a rewrite — the same rule applied to the event bus everywhere else.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

# channel -> set of subscriber queues
_subscribers: dict[str, set[asyncio.Queue]] = {}


def publish(channel: str) -> None:
    """Signal subscribers of `channel` that something changed. Non-blocking, drops on a full queue
    (a slow consumer must never back-pressure the trade path)."""
    for queue in _subscribers.get(channel, set()):
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass


@asynccontextmanager
async def subscribe(channel: str) -> AsyncIterator[asyncio.Queue]:
    """Subscribe to a channel for the duration of the context. Yields a queue that receives a
    signal (None) on every publish."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    _subscribers.setdefault(channel, set()).add(queue)
    try:
        yield queue
    finally:
        subs = _subscribers.get(channel)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                _subscribers.pop(channel, None)


def market_channel(symbol: str) -> str:
    return f"market:{symbol.upper()}"
