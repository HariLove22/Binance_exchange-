# Binance-class exchange in India — reality check

Research date: 2026-07-17. Re-verify anything marked ⚠️ before betting on it.

## The order of what kills you

1. **Banking partner** — no bank = no INR = no exchange. Hardest step. Not a code problem.
2. **FIU-IND registration** — mandatory, gating. No registration = platform blocked (happened to Binance, KuCoin, OKX, Huobi, Kraken, Bitstamp, MEXC, Bitfinex, Gate.io in Jan 2024).
3. **Liquidity** — an empty order book is worthless. Binance's moat is liquidity, not 1.4M ops/sec.
4. **Custody security** — one key leak = insolvency + criminal liability.
5. **The code** — genuinely the easiest part.

## India regulatory regime (as of Jan 2026)

**There is no crypto exchange licence in India.** No SEBI, no RBI licence. FIU-IND registration
under PMLA + AML compliance is the *entire* formal regime. Crypto is legal to trade, heavily
taxed, AML-regulated, otherwise unregulated (no consumer protection, no custody standard, no
capital adequacy, no proof-of-reserves mandate).

### FIU-IND registration
- PMLA s.2(1)(sa)(vi) — VDA Service Providers are "reporting entities" (March 2023 notification).
- **Activity-based, not location-based.** Offshore incorporation does not exempt you.
- FY2024-25: 49 VDA SPs registered (45 domestic, 4 offshore). ₹2.8bn penalties that year.
- Binance: blocked Jan 2024 → ₹18.82cr penalty → registered Aug 2024.

### FIU-IND AML/CFT Guidelines 2026 (issued 08 Jan 2026) — current bar
- Live-selfie with **liveness detection** at onboarding
- **Geo-tagging** of platform sessions
- **Penny-drop** bank account validation
- **Mandatory delisting of privacy coins** (Monero, Zcash shielded, mixer-adjacent)
- **Principal Officer must be India-based** — kills offshore-compliance structures
- Designated Director, CDD/EDD, 5-year retention, STR/CTR/NTR/CBWTR filing,
  FATF Travel Rule, UNSC + UAPA sanctions screening, board-approved AML policy, independent audit

Source: https://fiuindia.gov.in/pdfs/downloads/VDA08012026.pdf

### Tax — this is an architecture requirement, not an accounting one

| Provision | Rate | Detail |
|---|---|---|
| s.115BBH | 30% + 4% cess (~31.2%) | Flat, on VDA transfer income |
| s.115BBH deductions | **None** | Only cost of acquisition. No fees, no infra. |
| s.115BBH loss offset | **None** | Not even against other crypto gains. No carry-forward. |
| s.194S | **1% TDS** | On **gross sale consideration**, not gain. ₹50k/yr threshold (specified persons), ₹10k otherwise. |
| GST | 18% | On the exchange's fee revenue |
| Reporting | Schedule VDA, ITR-2/ITR-3 | FY2025-26 / AY2026-27 |

**Why 1% TDS is structural:** it hits gross turnover per transaction regardless of P&L. A trader
turning over ₹1cr/day pays ₹1L TDS whether they won or lost. This is mathematically fatal to
market making and HFT — and is why Indian exchange volumes fell ~90%+ after July 2022 and went
offshore. You cannot bolt this on later.

Must build: real-time TDS withholding in settlement, per-user cumulative threshold tracking,
Form 26QE/26Q filing, Form 16E certificates, per-user FIFO cost basis with no loss offset,
Schedule VDA statements. ⚠️ Crypto-to-crypto TDS is genuinely ambiguous in CBDT circulars —
exchanges implement it differently.

### Volatility risk
RBI remains institutionally hostile, publicly backed prohibition as recently as July 2026.
COINS Act 2026 (industry-drafted licensing framework) is circulating but **is not law**.
Treat any long-horizon plan as exposed to regime change.

### INR on-ramp reality
**P2P is the on-ramp.** No direct fiat rails. Binance discontinued cash for P2P in India.
UPI/IMPS/bank transfer/Paytm via P2P escrow only.

> **This inverts the usual build order.** Spot-first is the standard advice, but in India a spot
> exchange with no way to get INR in is a demo. P2P escrow is not a "phase 3 feature" — it is
> the deposit mechanism.

## Launch checklist (India)
Company/LLP incorporation → India-based PO + Designated Director → board-approved AML/KYC policy
→ FIU-IND registration → **banking partner (hardest)** → KYC vendor with Aadhaar/DigiLocker/PAN
+ liveness + penny-drop (Signzy/IDfy/Karza) → chain analytics (Chainalysis/TRM/Elliptic)
→ TDS engine → Schedule VDA reporting → ISO 27001 / SOC 2 for banking diligence

## Scope notes
- **NFT marketplace is dead.** Binance shut it; access ended 23:59 UTC 3 July 2026. Do not scope it.
- **Card is not an India product.**
- ⚠️ Exact fee/VIP tier numbers could not be verified — sources contradicted each other
  (VIP 1 quoted as both $250k and $1M volume; VIP 9 maker as both 0% and 0.011%).
  Read live from binance.com/en/fee/schedule.
- ⚠️ binance.com/en-IN homepage structure not reliably captured (fetch returned stale/cached
  render showing BTC ~$63k). Verify against a live logged-in session.

## The honest summary
The matching engine is the fun part and the smallest part. A technically perfect clone with no
INR banking rail and no FIU registration is a very fast way to display an order book to nobody.
