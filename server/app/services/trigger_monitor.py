"""Background watcher that fires stop orders.

A stop order rests OUTSIDE the book with no locked funds until its trigger price is crossed. Nothing
in a normal request path watches the live price, so this loop does: every few seconds it prices each
market that has a pending stop against the Binance feed and fires whatever has crossed, through the
normal lock+match path. It is the only moving part that makes conditional orders actually conditional.

One task per process, started/stopped by the app lifespan. Each sweep runs in its own short-lived
session and commits atomically; a failure in one cycle is logged and the loop continues — a monitor
that dies on a transient DB or network blip would silently strand every stop after it.
"""

import asyncio
import logging

from datetime import datetime, timezone

from app.core.db import AsyncSessionLocal
from app.services import futures, marketmaker, options, pubsub, trading

log = logging.getLogger("trigger_monitor")

# How often to price pending stops. Stops are not latency-critical (we are not a HFT venue), and the
# reference is a public feed we should not hammer; a few seconds is responsive without being abusive.
POLL_SECONDS = 3.0


async def _sweep_once() -> None:
    async with AsyncSessionLocal() as db:
        fired = await trading.sweep_triggers(db, marketmaker.fetch_reference_price)
        # Same loop liquidates underwater futures positions against the smoothed MARK price (not the
        # raw last price) — so a single wick can't trigger a liquidation.
        liquidated = await futures.sweep_liquidations(db, futures.mark_price)
        # And settles options that have expired, at the mark price.
        settled = await options.sweep_expiries(db, now=datetime.now(timezone.utc), price_of=marketmaker.fetch_reference_price)
        # And charges perpetual funding to positions whose 8h interval is due (on the mark price).
        funded = await futures.apply_funding(db, now=datetime.now(timezone.utc), price_of=futures.mark_price)
        # And fills resting futures LIMIT orders the last price has reached.
        fut_filled = await futures.sweep_orders(db, futures.last_price)
        if fired or liquidated or settled or funded or fut_filled:
            await db.commit()
            for symbol in fired:
                pubsub.publish(pubsub.market_channel(symbol))  # wake live subscribers
            if liquidated:
                log.info("liquidated futures positions: %s", liquidated)
            if funded:
                log.info("charged funding on %s positions", funded)
            if settled:
                log.info("settled options: %s", settled)
            if fired:
                log.info("fired stops: %s", fired)
            if fut_filled:
                log.info("filled futures limit orders: %s", fut_filled)
        else:
            await db.rollback()


async def run() -> None:
    """Poll forever. Cancelled by the lifespan on shutdown."""
    log.info("trigger monitor started (every %ss)", POLL_SECONDS)
    while True:
        try:
            await _sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a transient failure must not kill the monitor
            log.exception("trigger sweep failed; continuing")
        await asyncio.sleep(POLL_SECONDS)
