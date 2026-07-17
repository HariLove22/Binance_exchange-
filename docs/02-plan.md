# The plan

Constraints taken as given: real business, India, TS/React + Python, spot trading first.

## Three recommendations that change the brief

### 1. P2P is not phase 3. It's phase 1.
India has no direct fiat rails for crypto. INR gets in via P2P escrow (UPI/IMPS/bank transfer)
or it doesn't get in. A spot exchange with no INR on-ramp is a demo, not a business.
So: **spot engine + P2P escrow ship together, or nothing ships.**

### 2. Do not build custody. Buy it.
Fireblocks / Copper / BitGo. Building hot/warm/cold + HSM + MPC + reorg-aware indexers + sweep
logic across N chains is a 2-year project and an unbounded liability. Bybit lost $1.5B in Feb
2025 with the cryptography working perfectly — the approval UI was the hole. You will not beat
that with a first attempt. Buy custody, integrate, migrate in-house later if ever.

This also removes the single largest chunk of work from the roadmap.

### 3. Do not write the matching engine in Rust. Write it in TypeScript.
This will feel wrong. It isn't.

- Binance's 1.4M ops/sec is **aggregate across ~1400 symbols** — ~1000 ops/sec/symbol.
- You will not have 1400 symbols. You will have 5.
- You will not have 1000 ops/sec. You will have 0 for the first six months, because you will
  have no liquidity.
- A naive TS matching engine does tens of thousands of ops/sec. That is 10-100x your realistic
  year-one peak.
- **You are not latency-constrained. You are liquidity-constrained and licence-constrained.**

Write it in TS, in the language you're fast in. Ship. Get FIU-registered. Get a bank. If you ever
have a load problem, that is a *wonderful* problem and you rewrite the engine in Rust then — and
because it's a deterministic state machine with a journal, **you can replay production history
through the new engine and diff it against the old one to prove correctness.** The architecture
makes the rewrite safe. That's the whole point of the design.

The one thing you must NOT compromise: **determinism and integer math**. Get those right in TS
and the Rust port is mechanical. Get them wrong and no language saves you.

## Non-negotiables from day 1 (cheap now, impossible to retrofit)

1. **Integers everywhere.** `bigint` in TS, scaled to the asset's min unit. Never `number` for
   money. Never floats. API returns quantities as **strings**.
2. **Double-entry ledger.** Every movement balances to zero per asset. Append-only. The trial
   balance assertion runs in CI and in a continuous job.
3. **Determinism in the engine.** Time arrives as a command field. No `Date.now()`, no `Math.random()`,
   no unordered iteration, no I/O, no floats in engine code.
4. **Journal the input command stream.** Before the matcher acts.
5. **1% TDS in settlement.** Not a report. A ledger leg. Per-user cumulative threshold tracking
   from the first trade.
6. **Per-user FIFO cost basis, no loss offset.** Users cannot file their taxes without this.
7. **Idempotency keys** on every ledger transaction.

## Phases

### Phase 0 — decide if this is real (weeks, not code)
- Talk to a bank. Seriously, before writing anything. This is the step that kills projects and
  it is free to test. If no bank will talk to you, everything below is moot.
- Talk to a lawyer about FIU-IND registration + the Jan 2026 AML/CFT Guidelines.
  Note: **Principal Officer must be India-based.**
- Cost out KYC (Signzy/IDfy/Karza), custody (Fireblocks), chain analytics (Chainalysis/TRM).
  These are real recurring costs. Get quotes.

### Phase 1 — the engine, on fake money
No custody, no KYC, no bank. Paper trading only. Prove the core.
- Matching engine: LIMIT, MARKET, GTC/IOC/FOK, price-time priority, deterministic, integer math
- Sequencer + journal + replay
- Double-entry ledger with the trial-balance invariant enforced
- Balance lock/settle/release
- REST: place, cancel, open orders, trades. WS: trades, depth diff, klines
- React frontend: order book, chart, order form, open orders
- **The test that matters**: replay the journal, rebuild the book and the ledger from zero,
  diff against live state. Bit-identical or it's broken.

Deliverable: a working exchange with fake money. This is a genuinely impressive portfolio piece
even if the business never launches — and it de-risks everything downstream.

### Phase 2 — the boring stuff that makes it legal
- KYC vendor integration (Aadhaar/DigiLocker/PAN + liveness + penny-drop + geo-tagging)
- Custody integration (Fireblocks) — deposits, withdrawals, whitelist + time-lock
- TDS engine, Form 26QE/26Q, Form 16E, Schedule VDA statements
- AML: STR/CTR filing, Travel Rule, UNSC + UAPA screening
- Withdrawal approval tiers + circuit breaker + 24h freeze on credential change
- Audit log, 5-year retention

### Phase 3 — P2P escrow (the on-ramp)
- Ad posting, escrow lock at ad-post time (from Funding wallet)
- Order flow: open → 15-min payment window → mark paid → seller confirms → release
- Dispute/appeal + arbitration tooling
- Merchant reputation: completion rate, release time, order count
- **No cash.** UPI/IMPS/bank transfer only.

### Phase 4 — only if phases 1-3 have real users
Margin, futures, Earn, Convert, bots. Do not touch these before there are users. Futures needs
a whole separate risk engine (account-sharded, mark price, funding, liquidation, insurance
fund, ADL) — that is a bigger project than everything in phase 1.

**Never**: NFT marketplace (Binance shut theirs 3 July 2026). Card (not an India product).

## Order types — build in this order
1. LIMIT + MARKET, GTC — this is 95% of real volume
2. IOC, FOK (remember FOK's two-pass simulate flag)
3. LIMIT_MAKER (post-only) — market makers will ask for this first
4. STOP_LOSS_LIMIT / TAKE_PROFIT_LIMIT — needs the conditional-order store, outside the book
5. OCO — needs the order-list entity; same-symbol only
6. Iceberg, trailing stop — later

## The thing to internalize
The matching engine is the fun part and the smallest part. Binance's moat is not throughput —
it's liquidity, a decade of banking relationships, and having survived a $4.3B settlement.

Build phase 1 because it's tractable and it proves you can. But **phase 0 decides whether this
is a business.** Do phase 0 first.
