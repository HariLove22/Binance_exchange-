# Wallet architecture

How the wallet works, and what we build vs rent. Written before the code, so the shape is a
decision and not an accident.

## The one idea

**A wallet balance is a database row, not coins on a chain.** When a user "holds" 1 BTC, they
hold a ledger entry asserting a claim; the actual BTC sits in a pooled custody wallet mixed with
everyone else's. This is why trading is instant — a trade mutates two rows, nothing touches a
blockchain. The chain is involved at exactly two edges: **deposit** (money in) and **withdrawal**
(money out). Everything between is the ledger.

> Wallet = ledger. Blockchain only at the edges.

## Two halves

```
INTERNAL LEDGER (we build)          EXTERNAL CUSTODY (we rent)
- per user, per asset               - hot / warm / cold wallets
- available / locked                - deposit addresses
- double-entry, atomic, idempotent  - private keys (HSM / MPC)
- trades settle here                - on-chain broadcast
        \                                    /
         \____ DEPOSIT + WITHDRAWAL + RECONCILIATION ____/
```

- **Internal ledger** — we build this. It is the heart of the wallet.
- **Private keys / custody** — we never build. Fireblocks / BitGo / Turnkey / Tatum. Building it
  is a multi-year project whose failure mode is total loss of customer funds.
- **Deposit / withdrawal pipeline** — we build this. It is the same regardless of which custody
  provider sits behind it, which is why it goes behind a `CustodyProvider` interface: a mock /
  testnet adapter now, a real provider later, one class swapped, no rewrite.

## Sub-wallets

Binance shows Spot, Margin, Funding, Futures as separate balances; transferring between them is an
internal ledger move, not a chain transaction. **We build Spot only for now.** Funding and Margin
are added later via a `wallet` column on accounts — additive, not a rewrite. Nothing here assumes
Spot is the only wallet that will ever exist.

## Account model (double-entry)

Every balance change is a transaction of entries that sum to zero, per asset. Money is never
created or destroyed, only moved.

```
accounts(user_id NULL, asset_id, account_type)   -- balance is cached, entries are truth
  user types:   AVAILABLE, LOCKED
  system types: EXTERNAL, FEE_INCOME, TDS_PAYABLE
ledger_transactions(idempotency_key UNIQUE, kind)
ledger_entries(transaction_id, account_id, asset_id, amount)   -- append-only
```

- **AVAILABLE** — spendable. What the user sees as their balance.
- **LOCKED** — reserved against an open order. Still theirs, not spendable twice.
- **EXTERNAL** — the outside world. A deposit is a transfer from EXTERNAL to the user, so EXTERNAL
  goes negative and its magnitude is what we should be holding on-chain. Reconciling the two is
  how theft and bugs are found.
- **TDS_PAYABLE** — 1% withheld on VDA transfers under Indian rules. Present from day one because
  bolting it on later means reprocessing every trade.

Invariants enforced in the database, not in review comments:
1. Entries reject UPDATE and DELETE (append-only). Corrections are compensating transactions.
2. Every transaction sums to zero per asset (a deferred constraint trigger).
3. An entry's asset matches its account's asset.
4. User balances never go negative (only EXTERNAL and TDS_PAYABLE may).

## Deposit flow

```
address (per user, per network) → user sends on-chain → node/webhook detects
  → wait N confirmations (scaled by value) → AML screen source
  → CREDIT ledger EXTERNAL → user AVAILABLE (idempotent on tx_hash) → sweep to hot wallet
```

- Idempotent on `tx_hash`: webhooks retry, a double credit is money gone.
- Reorg-aware: track `(height, block_hash)`; on mismatch, unwind deposits from the orphaned chain.
- Confirmations scale with value: 0.001 BTC at 1, 500 BTC at 6+ and a human.

## Withdrawal flow

```
request → validate (address, min, balance) → 2FA + email
  → new address gets a 24-72h whitelist cooldown → risk screen (velocity, OFAC)
  → DEBIT AVAILABLE, credit PENDING_WITHDRAWAL  (the accounting boundary is here, not at broadcast)
  → approval tier → signer (HSM/MPC) → broadcast → confirm → finalise to EXTERNAL
```

## Reconciliation

A continuous job: `sum(user balances) + fees == on-chain holdings`. On mismatch, halt withdrawals
and page a human. Not optional — it is what catches both bugs and theft.

## What we build now, in order

1. **Ledger core** — accounts, transactions, entries; double-entry, atomic, idempotent, with the
   trial-balance invariant in the database.
2. **Wallet API** — `GET /wallet/balances`, so the dashboard's `0.00` becomes real.
3. **Assets / chains** — express "USDT on TRON".
4. **Deposit flow** — behind a mock `CustodyProvider`, testnet addresses, simulated confirmations.
5. **Withdrawal flow** — same interface, mock signer.
6. **Reconciliation** — ledger vs custody.

Custody stays a mock until an entity and a provider account exist (see `docs/02-plan.md`). Every
step above is real and permanent; only the provider behind the interface changes.
```
