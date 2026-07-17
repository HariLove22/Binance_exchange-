# Exchange architecture — the parts that matter

Condensed from research 2026-07-17. Binance publishes almost nothing about internals; much of
this is reconstructed from their public API semantics + standard exchange practice (LMAX,
Nasdaq INET, CME). Their API *semantics leak their architecture* — that's the most reliable source.

## 1. Matching engine

**Single-threaded, in-memory, deterministic state machine per symbol.** This is not a
performance compromise — it is the design. Determinism is what makes journaling, replay, crash
recovery and hot-standby failover possible. Everything that is not matching (auth, risk,
sequencing, market-data fanout, persistence) moves off the hot thread.

```
OrderBook { bids: PriceLevel[] desc, asks: PriceLevel[] asc }
PriceLevel { price: i64 (scaled ticks), total_qty: i64, orders: intrusive FIFO list }
orders_by_id: HashMap<OrderId, *Order>   // O(1) cancel — 90-95% of messages are cancels
```

**Price-time priority (FIFO).** Critical subtlety: **timestamps are not the priority key** —
the sequencer's monotonic sequence number is. Two orders can share a millisecond. This is also
what makes replay bit-identical.

**Banned from engine code** (any one of these makes a hot standby diverge silently):
system clock reads, unordered map iteration, floating point, `random()`, I/O.
Time arrives as a *field in the command*, stamped by the sequencer.

### About "1.4M orders/sec"
- It is **aggregate across ~1400 symbols**, not per book. ~1000 ops/sec/symbol average.
- "Orders" counts all book mutations — new, cancel, amend. ~90%+ is market-maker cancels.
- A single well-written single-threaded engine does 5-20M ops/sec on one core.
  LMAX's Disruptor benchmark: ~25M msg/sec on one thread, sub-50ns.
- **The hard part is ingress, not matching.** Do not let this number scare you.

### Sequencer + journal
```
Gateways ──▶ Sequencer (stamps seq) ──┬──▶ Journaller ──▶ append-only log (batched fsync)
                                       ├──▶ Replicator ──▶ hot standby
                                       └──▶ Matcher ──▶ trades + deltas ──▶ Publisher
```
After the sequencer, the system is `state[n] = f(state[n-1], cmd[n])`.
Journal the **input command stream**, not the state. Recovery = snapshot + replay tail.
Snapshot every N million events **from a replica**, so the hot path never pauses.

The Disruptor insight: journal write, replication send, and business logic run **in parallel,
not in sequence** — all three consumers read the same ring slot. The matcher's output is gated
on journaller+replicator passing that seq. Durability without serializing the work.

## 2. Order lifecycle

```
NEW ──┬──▶ PARTIALLY_FILLED ──┬──▶ FILLED (terminal)
      │                        └──▶ CANCELED (retains executedQty > 0)
      ├──▶ FILLED
      ├──▶ CANCELED
      ├──▶ REJECTED (never entered book)
      ├──▶ EXPIRED (IOC/FOK residual, delisting)
      └──▶ EXPIRED_IN_MATCH (self-trade prevention)
```

| Type | Notes |
|---|---|
| LIMIT | needs timeInForce |
| MARKET | `quantity` OR `quoteOrderQty` ("spend exactly 100 USDT"). Implicitly IOC. |
| STOP_LOSS / STOP_LOSS_LIMIT | stopPrice or trailingDelta |
| TAKE_PROFIT / TAKE_PROFIT_LIMIT | opposite side trigger |
| LIMIT_MAKER | post-only. Rejected outright if it would match. Implicitly GTC. |

**Trigger orders live OUTSIDE the book** — separate conditional store keyed by
`(symbol, stopPrice, direction)`. A monitor watches last-trade (or mark) price and injects a
real order into the sequencer on crossing. So: stops consume no book memory, trigger→fill
slippage is real and unavoidable.

**OCO** = order list of exactly 2 legs (one maker/TP leg, one stop leg). Consumes 2 order slots.
The sibling-cancel is a *sequenced command*, not atomic — the window where both fill is closed
by handling the OCO cancel **inside the same engine tick**, which works only because both legs
are same-symbol → same shard. **This is why sharding is by symbol, and why OCO is same-symbol
only: a shard boundary leaking into the product surface.**

**Iceberg**: only `icebergQty` displayed; each refill **loses time priority** (re-queued at back).
Forced to GTC.

| TIF | Engine implementation |
|---|---|
| GTC | insert residual into book |
| IOC | walk book, do not insert residual |
| FOK | **two-pass**: dry-run walk to verify full qty, then commit. Must not mutate on the failed pass. |

FOK's two-pass is why the walk function takes a `simulate` flag — you cannot match-then-rollback
in a single-threaded engine without unwinding published trades.

**Filters are enforced at the gateway, before the sequencer.** The engine must never reject for
a business-rule reason — that's a divergence risk and a wasted sequencer slot.

## 3. Ledger

### Never floats. Ever.
`0.1 + 0.2 != 0.3`. double = 53-bit mantissa ≈ 15.95 decimal digits. 21M BTC in satoshis needs
2.1e15 — **right at the edge**, and any intermediate multiply blows past it. Wei (1e18) is hopeless.

- **Engine**: scaled i64/i128 in the asset's min unit. price×qty needs i128 intermediate.
- **Ledger**: Postgres `NUMERIC(36,18)` / Python `Decimal` / Java `BigDecimal` with explicit
  MathContext + RoundingMode. 10-100x slower than ints — fine for the ledger tier, never the hot path.
- **JSON is a landmine.** Binance returns quantities as *strings* (`"0.00100000"`) precisely so
  naive clients don't parse them into doubles. Any clone must do the same.
- **Rounding is a business decision.** Explicit, consistent, conservative. When splitting a fee,
  allocate the remainder deterministically to one party — rounding each independently creates dust.

### Double-entry
```sql
accounts(id, user_id NULL, asset, account_type)  -- AVAILABLE|LOCKED|FEE_INCOME|HOT_WALLET|
                                                 -- COLD_WALLET|INSURANCE_FUND|EXTERNAL
  UNIQUE(user_id, asset, account_type)
transactions(id, idempotency_key UNIQUE, kind, created_at)
entries(id, transaction_id, account_id, asset, amount NUMERIC(36,18) CHECK(amount<>0))
```

**Invariants — assert in CI and in a continuous reconciliation job:**
1. `SELECT asset, SUM(amount) FROM entries GROUP BY asset` → **0 for every asset, always.**
   Nonzero = you created or destroyed money.
2. Entries are **append-only**. No UPDATE, no DELETE. Corrections are compensating transactions.
3. Every transaction balances **per asset independently** (a BTC/USDT trade has 4+ entries and
   must sum to zero in BTC *and* in USDT).
4. AVAILABLE and LOCKED never negative (except flagged margin accounts).
5. `SUM(user balances) + fee_income + insurance_fund == on-chain holdings` — proof-of-reserves.

A spot trade (A buys 1 BTC @ 50k from B, 0.1% both sides):

| Account | Asset | Amount |
|---|---|---|
| A:LOCKED | USDT | −50,000 |
| B:AVAILABLE | USDT | +49,950 |
| FEE_INCOME | USDT | +50 |
| B:LOCKED | BTC | −1.0 |
| A:AVAILABLE | BTC | +0.999 |
| FEE_INCOME | BTC | +0.001 |

Both columns sum to 0. (For India, add the 1% TDS leg → a TDS_PAYABLE account.)

### Balance locking
**Lock on submit, settle on fill, release on cancel.** The lock **must** happen before the order
reaches the sequencer — otherwise the engine can produce a trade the ledger can't fund.

Scaling ladder: `SELECT..FOR UPDATE` (fine to ~5-10k TPS/row, start here) → optimistic + version
→ **actor/single-writer per account** (consistent hash user_id → thread; mirrors the engine's design)
→ in-memory balance cache with write-behind journal (a second deterministic state machine).

**Ordering hazard**: locking is user-sharded, matching is symbol-sharded; a trade mutates two
users across two shards. Answer: **settlement is asynchronous and eventually consistent behind
the engine** (via Kafka). This is correct — the pre-trade lock already guarantees solvency;
settlement is bookkeeping, not authorization. Do not reach for 2PC.

Clearing must be **idempotent** (keyed on trade_id — the UNIQUE constraint gives you exactly-once
for free) and **ordered per account** (partition Kafka by user_id, even though the engine
partitions by symbol — that's a repartitioning shuffle).

> Highest-value correctness check in the whole system: a nightly job that replays the engine
> journal and diffs the result against the ledger.

## 4. Wallet — the highest-risk component

| Tier | Funds | Purpose |
|---|---|---|
| Hot | 2-5% | automated withdrawals, HSM/MPC policy-signed |
| Warm | 10-15% | hot refill, human quorum |
| Cold | 80-95% | air-gapped, multi-site, M-of-N ceremony |

**Design goal: a total compromise of every online system must cap losses at the hot balance.**
If root on your withdrawal service drains >5%, your architecture is wrong. Design backwards
from this.

### HD wallets — the xpub trick (most important wallet decision, and it's free)
Non-hardened child *public* keys derive from the parent *public* key alone. So:
- Master private key **never leaves cold storage / HSM**.
- Export `xpub` at `m/44'/0'/0'` to the online deposit service.
- Service derives `m/44'/0'/0'/0/{user_index}` **public keys only** → unlimited per-user deposit
  addresses with **zero private key material online**.

**The hardening trap**: the last two levels are non-hardened *so that this works*. But
**xpub + any one non-hardened child private key = the parent private key** (algebraically
solvable). xpub leak alone = privacy problem. xpub + one leaked child key = **total compromise**.
Hence hardening at `account'` — it firewalls each account so a breach can't climb the tree.

### Deposit pipeline
```
Own node (Geth/Erigon/Reth/Bitcoin Core) → ingester (sequential by height, gap-aware)
  → indexer (match against watched address set; Bloom filter / Redis SET)
  → DETECTED (0 conf) → confs++ per block → CONFIRMED → credit (EXTERNAL → user:AVAILABLE)
  → sweep to hot/omnibus
```
- **Never trust Infura/Alchemy as the sole source of truth for deposits.** Run your own nodes,
  ideally 2 independent implementations per chain for cross-validation. A node lying about a
  block is a direct path to crediting a nonexistent deposit.
- **Reorg handling is where exchanges get robbed.** Track `(height, block_hash)`; on hash
  mismatch at a known height, unwind every deposit from the orphaned chain.
- **Confirmation count must scale with deposit value.** 0.001 BTC at 1 conf is fine;
  500 BTC should wait 6+ and probably a human.

Representative: BTC 1-2 · ETH 6-12 (wait for **finalized**, 2 epochs ≈12.8min, for large)
· BSC 15 · Polygon 100-300 · Tron 19-20 · Solana 1 (`finalized` commitment — optimistic ≠ finalized)
· XRP/XLM 1.

Chain models: UTXO + account chains → per-user HD address. **XRP/XLM/EOS/ATOM/TON → single
shared address + memo/tag** (this is why "you forgot the memo, funds are lost" tickets exist).

**The ETH sweep gas problem**: to sweep USDT from a per-user address you must first send ETH
*to* it for gas, then send the ERC-20 out — 2 txs per sweep. Options: CREATE2 per-user deposit
contract swept by a factory, EIP-4337/7702 sponsored sweeps, batch when gas is cheap, or eat it.

### Withdrawal
```
request → 2FA + email + (new address → 24-72h whitelist cooling period)
       → risk: velocity, address screening (Chainalysis/TRM), OFAC, device fingerprint
       → ledger: debit AVAILABLE, credit PENDING_WITHDRAWAL  ← the accounting boundary is HERE,
                                                                not at broadcast
       → tiered approval → HSM/MPC signer → own node broadcast → confirm watcher → COMPLETED
```

**The signer must be the policy enforcement point, not the application.** It must independently
re-verify destination whitelist, amount, tier limit, approver signatures, rate limit. If it
trusts the caller, your security boundary is your least-patched microservice.

**Nonce management**: concurrent signers on one hot address produce duplicate nonces → stuck
queue. Single-writer nonce allocator per address.

Controls that actually matter: address whitelist **with time-lock** (defeats the entire
"attacker has full session control" class — they must hold access 24h without the user noticing
an email) · global withdrawal circuit breaker on anomalous net outflow · 24h withdrawal freeze
on any credential change.

> **Bybit lost $1.5B (Feb 2025) with the cryptography working perfectly** — approvers signed a
> transaction whose displayed contents differed from its payload. **The attack surface is the
> approval UI, not the key.** Blind-signing is the vulnerability.

### MPC vs Multisig vs HSM — honest framing
- **MPC's real win is operational**, not cryptographic: chain-agnostic, one normal-looking
  signature on-chain (cheap, private), proactive share refresh without moving funds.
- **Multisig's real win is transparency**: enforced by the chain itself, publicly verifiable,
  15 years of understood failure modes. MPC security = one library's implementation of a hard
  protocol (GG18 had real key-extraction bugs in 2023).
- Same threat model for both: no single machine/person/datacenter can move funds.
- **Neither helps if the policy layer is compromised.**

## 5. Market data

Streams: `@trade` `@aggTrade` `@depth` (diff) `@depth{5|10|20}` (partial snapshot) `@kline_*`
`@ticker` `@bookTicker` `@miniTicker`. Depth speed 100ms/1000ms.

### The snapshot+delta sync algorithm — everyone gets this wrong
1. Open WS. **Buffer events, do not apply.**
2. GET REST snapshot (`limit=5000`).
3. Drop buffered events where `u <= lastUpdateId`.
4. First event to apply must satisfy `U <= lastUpdateId+1 <= u`. If none does → **snapshot is
   stale, go back to step 2.**
5. Apply. `local_id = u`.
6. Every subsequent event: assert `U == local_id + 1`. **Fail → book is corrupt → tear down and
   resync. Do not patch.**
7. Applying: `qty == 0` → delete level; else **absolute-set** the level.

Traps: `qty` is an **absolute replacement, not a delta** — "diff depth" is a misleading name;
it's a *level-set* stream. And deltas touch levels outside your snapshot depth, so
**always snapshot deeper than you intend to track**.

> Resync is always cheaper than a wrong book.

### Feed handler
**Conflation is mandatory.** BTCUSDT generates >100k book updates/sec; 99% is post/cancel churn
at the same level. Per symbol, keep a dirty-level set; every 100ms emit ONE event with the net
change. ~1000x bandwidth reduction. *This is why Binance offers 100ms/1000ms and not "every update".*

**Serialize once, send N times.** 500k connections on BTCUSDT → serializing per-subscriber is
500k× wasted CPU. Serialize into a refcounted buffer, `writev` the same bytes to every socket.

**Slow consumers must never back-pressure the publisher.** Bounded per-conn queue → disconnect
on overflow (Binance's choice). **The MD path must never back-pressure the engine.**

Binance puts snapshots on REST (cacheable, CDN-able) and diffs on WS — a deliberate offload:
snapshot generation is expensive and cacheable, diffs are cheap and must be live.

### Klines
A **fold over the trade stream**, not the book. Subtleties: **empty buckets** must synthesize a
flat candle at prior close or charts gap. Higher intervals fold from lower (1m→5m→1h), not
recomputed from trades. `1M` is **calendar-aligned, not 30-day**. The `x` (isClosed) field is
what makes a candle final — **consuming un-closed candles as final is the #1 backtest/live
divergence bug.**

## 6. Risk engine (futures — later phase, but design ledger for it now)

- **Isolated**: `MarginRatio = maintMargin / (isolatedMargin + uPnL)`. Single-shard liquidation.
- **Cross**: `MarginRatio = Σ maintMargin / (wallet + Σ uPnL)`. **The account is the transaction
  boundary, not the symbol** → the risk engine shards by *account*, not symbol, and is a separate
  service from the matcher.

**Tiered maintenance margin**: `maintMargin = notional × MMR(tier) − maintAmount(tier)`.
The `maintAmount` subtraction makes the piecewise function **continuous** at bracket boundaries —
without it, +$1 of notional at a boundary would step-change your margin and cause an instant
liquidation. Same trick as a progressive tax bracket. Crossing a bracket silently cuts your
effective max leverage — that's how a "safe" 10x gets liquidated at a price it shouldn't.

**Mark price ≠ last price.** Mark determines uPnL and liquidation. If liquidation used last
price, a whale could push a thin book 10% for 200ms and harvest every long. Mark is
`Median(index + MA(basis), index·(1+funding·t), lastPrice)` — **median-of-three: to move the
mark you must move two of three independent inputs.** Index itself is a multi-venue
outlier-filtered weighted average. This is the single most important anti-manipulation
mechanism in derivatives.

**Funding** = peer-to-peer, exchange takes zero cut. Interest 0.01%/8h, damper clamp ±0.05%,
cap ±2% (or ±0.75×MMR). Charged **only to positions open at the exact timestamp** — not accrued
— which creates the flip-flat-before-funding arb. Premium is sampled **every minute and
averaged**, and uses **Impact Margin Notional** (depth-weighted, not top-of-book) — both are
anti-manipulation choices.

**Loss waterfall**: trader's margin → liq engine fills better than bankruptcy price → Insurance
Fund → **ADL** → (never) exchange balance sheet.
ADL score = `profit_ratio × leverage` (if profitable) — the most profitable, most leveraged
traders get force-closed first. Deeply unpopular, but the alternative is socialized clawback or
insolvency. A rapidly shrinking insurance fund during a crash is the leading indicator of ADL.

**Cascade risk**: liquidations are market orders → move price → trigger more liquidations.
Mitigated by tiered/partial liquidation, mark-price triggering, rate-limiting liq order flow
into the book, and the leverage brackets themselves.

## 7. Stack

**What Binance uses**: C++ engine · Java/Spring Boot/**Dubbo** + Go services · Python for
quant/ML · Kafka + RabbitMQ · **MySQL** + Redis · AWS + Alibaba Cloud (multi-cloud is how they
survived forced regulatory migrations). The Dubbo+Alibaba Cloud+MySQL combination is a tell:
this is a Chinese hyperscale-web stack applied to finance, not a Wall Street stack — which is
why it's horizontally-sharded microservices rather than a monolithic clearing system.

**What a 2026 clone should use** — but see 03-plan.md; most of this is premature for v1:

| Layer | Choice | Why |
|---|---|---|
| Engine | **Rust** (or C++23) | No GC. Not Go — you can't turn the GC off and `runtime.mallocgc` shows up in p99.9. Not Java unless you'll do LMAX-grade zero-alloc off-heap — at which point you've written C in Java. |
| Gateway | Go or Rust (axum/tokio) | I/O bound; goroutines are genuinely good at 500k conns |
| Bus | Redpanda or Kafka+KRaft | Redpanda for p99, Kafka for ecosystem |
| Ledger | Postgres NUMERIC, or **TigerBeetle** | TigerBeetle is purpose-built for double-entry, 1M+ transfers/sec, enforces debit/credit invariants *in the database*. Biggest "wish I'd known" for a 2026 ledger. |
| Klines | ClickHouse | nothing else is close for OHLCV at volume |
| **Custody** | **Fireblocks / Copper / BitGo — do NOT build** | 2-year project and a career-ending liability. Buy it. |
| KYC (India) | Signzy / IDfy / Karza | Aadhaar/DigiLocker/PAN + liveness + penny-drop |
| Chain analytics | Chainalysis / TRM / Elliptic | mandatory for licensing |
| Observability | OTel + Prometheus + Grafana + **HdrHistogram** | never averages — the mean latency of a trading system is a meaningless number |
| Deployment | k8s for stateless tiers; **bare metal, CPU-pinned, no containers for the engine** | do not run a latency-critical pinned single-threaded engine on a throttled cgroup-limited virtualized core |

## 8. Scaling

**Shard by symbol** — spot symbols share no state, so no distributed transaction is ever needed.
Not perfectly free though: **hot shard problem** (BTCUSDT is 100x ETHDOGE — you can't hash
uniformly; BTCUSDT/ETHUSDT get dedicated hosts, the long tail packs many-per-host), cross-symbol
atomicity breaks, and rebalancing is a halt-drain-snapshot-resume migration.

**Three different sharding keys**: symbol (engine), user_id (ledger), account_id (risk).
The repartitioning shuffles between them are Kafka's actual job here.

**Kafka is NOT on the matching hot path.** Kafka's p99 is milliseconds; the engine's is
microseconds. Put Kafka between gateway and engine and you've built a 5ms exchange. The engine's
durable log is its own mmap'd journal. Kafka is the *distribution* bus for everything downstream.

**Exactly-once is a lie you don't need** — at-least-once + idempotent consumers keyed on
trade_id. The `UNIQUE(idempotency_key)` constraint *is* your exactly-once. Simpler, faster,
actually correct.

**CQRS**: `POST /order` → engine. `GET /myTrades` → Postgres projection off Kafka. Different
systems. The trap is read-after-write 404s; **Binance solves it by returning the full
executionReport synchronously in the POST response, so the client never needs to read back.**
Design the API so read-after-write is never necessary — that's the correct CQRS answer, not
"make the projection faster."

**Event sourcing**: the journal is truth; the order book and balances are materialized views.
Gives you crash recovery, hot standby, regulatory reconstruction ("what was the book at
14:32:07.123456 on March 4?"), forensics against real production input, and the ability to
**fix a bug and replay history through the fixed code** to see what should have happened.
Determinism is the price of admission.

## 9. Security

Rate limiting is **multi-dimensional token buckets**: REQUEST_WEIGHT (per IP/min, per-endpoint
weights), ORDERS (per account, 10s + daily windows), RAW_REQUESTS, connection caps.
429 → back off. **418 → you are IP-banned** for continuing after 429s. Bans scale 2min → 3 days
and are **IP-based, not key-based** (a rogue bot on your NAT bans the whole office).

> Nice detail: the ORDERS limiter counts **unfilled** orders — *"if your orders are consistently
> filled by trades, you can continuously place orders."* Binance is rate-limiting **noise, not
> volume**. The limiter is a market-quality mechanism, not just a capacity one.

Implementation: Redis token bucket costs a round-trip per request you can't afford at the
gateway — approximate locally per-node, reconcile periodically, exact at a lower tier.

**Separate market data from trading infrastructure.** A volumetric attack on `/api/v3/depth`
must not degrade order entry. Binance does exactly this — `data-api.binance.vision` is a
separate host. **Cost asymmetry is the whole game**: if an unauthenticated request can cause a
database query, you have a DDoS amplifier.

API keys: HMAC-SHA256 / **Ed25519** (fastest, Binance's recommendation) / RSA. Timestamp +
recvWindow prevents replay. **Withdrawal permission on a key should require IP whitelisting,
full stop.**

Self-trade prevention (`EXPIRED_IN_MATCH`, modes NONE/EXPIRE_TAKER/EXPIRE_MAKER/EXPIRE_BOTH) is
both client protection and a **market-integrity control — wash trading is a regulatory landmine.**
