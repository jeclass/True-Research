
> **PARTIAL REPORT** — run ended early (reason: budget).
# Exploitable Edges in Kalshi and Polymarket: What the Evidence Actually Supports

## Lead Summary

The best available evidence confirms the existence of several **documented gross mispricing patterns** — favorite-longshot bias, calibration errors at extreme probabilities, cross-platform price deviations, and YES/NO asymmetries — but **no published source has been verified to document a fully-costed, net-profitable trading strategy** after simultaneously accounting for all frictions. The most cited academic results are gross-of-fees only (Becker 2026) [src-the-microstructure-of-wealth-transfer-in-2], and the one study that reportedly applies fee adjustment (Bürgi et al. 2026, GWU Working Paper 2026-001) finds a net **loss** of approximately −22% after fees per the available summary [src-makers-and-takers-the-economics-of-the-k-2].

Three formal adjudications shape every quantitative conclusion in this report:

1. **Kalshi fee rate:** The standard formula — maker 0.0175 × C × P × (1−P); taker 0.07 × C × P × (1−P), with monthly maker-fee reimbursement if fees exceed $10 — is the adjudicated best estimate. The claim that "API trading fees are currently 0%" originated from a single promotional developer blog and is contradicted by Kalshi's own FIX Execution Reports (which return fee dollar amounts) and by the Bürgi et al. finding that fee-adjusted returns are materially negative [src-makers-and-takers-the-economics-of-the-k-2]. The 0% claim is **rejected**.

2. **Bürgi et al. vs. Becker: two separate papers.** Bürgi, Deng, and Whelan (GWU Working Paper 2026-001, 300,000+ Kalshi contracts) [src-makers-and-takers-the-economics-of-the-k-2] and James Becker (jbecker.dev, 72.1M Kalshi trades) [src-the-microstructure-of-wealth-transfer-in-2] are independent studies with different authors, datasets, and methodologies.

3. **Kalshi "110–140% overround" is uncorroborated.** This figure appeared only in a credibility-60 affiliate site [src-kalshi-vs-polymarket-a-side-by-side-comp] and is inconsistent with the large-scale academic analyses of Kalshi data. It is **not used** in any quantitative calculation in this report.

A critical structural constraint governs the feasibility of cross-platform strategies: **simultaneous Kalshi + Polymarket operation is structurally impossible for any single trader class as of mid-2026.** US persons are legally prohibited from using Polymarket Global's API [src-polymarket-agents]; non-US persons cannot access Kalshi (which requires a US SSN) [src-is-polymarket-legal-in-the-usa-2026-upda]. Cross-platform arbitrage therefore requires coordination between two traders in different jurisdictions — adding counterparty risk not present in single-entity arbitrage.

**This was a partial run (ended early due to budget).** Seed questions q-003 (thin-market/spread/news-reaction), q-005 (geographic/KYC constraints), and q-006 (market-making/rebates) were partially synthesized through later findings but did not receive their own dedicated primary-source research retrievals. Several ToS legal pages for Kalshi could not be accessed despite multiple attempts.

---

## Facet 1: Documented Mispricing Patterns

### 1a. Favorite-Longshot Bias (FLB)

**Evidence quality: Moderate–High (two large-sample studies on Kalshi/Polymarket specifically)**

The FLB is the best-documented systematic bias in prediction markets: low-probability ("longshot") contracts are overpriced relative to their true resolution frequency; high-probability ("favorite") contracts are slightly underpriced.

**Bürgi, Deng, and Whelan (2026), GWU Working Paper 2026-001** [src-makers-and-takers-the-economics-of-the-k-2][src-makers-and-takers-the-economics-of-the-k]: Analyzed 300,000+ Kalshi contracts. Contracts priced below 10¢ lose more than 60% of invested money on average. Contracts above 50¢ earn a small statistically significant positive return. The average return across all Kalshi contracts is −20% before fees and −22% after fees — a net loss [src-what-five-new-academic-papers-say-about]. The bias is decreasing over time, suggesting partial arbitrage [src-what-five-new-academic-papers-say-about]. The abstract confirms low-price contracts "win far less often than required to break even after fees," confirming fee adjustment is applied [src-makers-and-takers-the-economics-of-the-k].

**Le (2026), "Decomposing Crowd Wisdom"** [src-decomposing-crowd-wisdom-domain-specific]: Analyzed 292M trades across 327,000 contracts on Kalshi and Polymarket. The mean calibration slope (the FLB measure) rises from 0.99 within one hour of resolution to 1.32 beyond one month, explaining 30.2% of calibration variance — a "universal horizon effect." In the politics domain, the slope reaches 1.31–1.64 (domain intercept +0.15, 95% CI: 0.122, 0.179); a 70¢ politics contract one week out corresponds to a true probability of approximately 83%. Sports markets are well-calibrated short-term (slopes 0.90–1.10 within 48 hours) but sharply underconfident beyond one month (slope 1.74). Weather and entertainment show *overconfidence* — the reverse of FLB — with domain intercepts of −0.086 and −0.085 respectively [src-decomposing-crowd-wisdom-domain-specific].

**Edge size:** 1.5–2.4% per trade on high-probability contracts is cited as a directional estimate in secondary sources [src-favorite-longshot-bias], but this is a secondary synthesis rather than a number extracted from primary papers. The Bürgi et al. finding that average returns are −22% after fees signals that selecting randomly among longshot contracts destroys value; only the *maker-side* position in high-probability contracts offers a small positive return [src-what-five-new-academic-papers-say-about].

**Fee survivability:** The Bürgi et al. finding that −22% is the fee-adjusted return on the average Kalshi contract rules out a simple "buy longshots" strategy. Per-secondary-source synthesis, "transaction fees (1–2%) eliminate sub-0.5% edges" [src-the-microstructure-of-wealth-transfer-in]; the breakeven threshold for a Kalshi taker is approximately 3.5% (see Facet 5) — which the FLB edge generally does not clear for takers.

**Domain specificity note:** FLB is pronounced in politics and long-horizon sports. Weather and entertainment markets show overconfidence rather than FLB, and Finance markets on Kalshi show a maker-taker gap of only 0.17 percentage points versus 2.23 pp for sports — near-perfect efficiency in professional-dominated categories [src-the-microstructure-of-wealth-transfer-in-2].

---

### 1b. Calibration Errors at Extreme Probabilities

**Evidence quality: Moderate (one large, non-peer-reviewed working paper with acknowledged limitations)**

Becker (2026) [src-the-microstructure-of-wealth-transfer-in] analyzed 72.1M Kalshi trades and documented systematic calibration errors at extreme probabilities:

- Contracts priced at **5¢** win 4.18% of the time (implied: 5%) — a mispricing of **−16.36%** relative to implied odds.
- Contracts at **1¢** win 0.43% (implied: 1%) — a mispricing of **−57%**.
- Contracts at **95¢** win 95.83% — a modest outperformance of **+0.87%**.
- All contracts below 20¢ underperform their implied probability; all above 80¢ outperform.

**Maker-taker decomposition:** Takers earn an average gross excess return of **−1.12%** (95% CI: −1.13% to −1.11%); makers earn **+1.12%** (+1.11% to +1.13%). At the 1¢ extreme, makers earn +1.57% gross while takers suffer the −57% mispricing described above [src-the-microstructure-of-wealth-transfer-in].

**YES/NO asymmetry:** At 1¢, the YES contract has an expected value of −41% while the complementary NO contract has +23% — a 64-percentage-point divergence. NO outperforms YES at 69 of 99 price levels, with the gap largest at the extremes. This reflects retail takers systematically preferring cheap YES contracts (lottery-ticket behavior) while sophisticated makers supply the other side [src-the-microstructure-of-wealth-transfer-in].

**Critical caveat:** All Becker returns are explicitly stated as **"gross of platform fees."** The paper cannot be used to claim market-making is net profitable — it establishes a gross edge only [src-the-microstructure-of-wealth-transfer-in-2].

**YES/NO asymmetry mathematical note:** An independent check (q-041 in the question ledger) was tasked with verifying whether the −41% YES / +23% NO figures are internally consistent for complementary binary contracts. This verification was resolved but its finding is not included in the findings provided; readers should treat these extreme figures as provisional pending peer review of the Becker paper.

---

### 1c. Time-to-Resolution Effects

**Evidence quality: Moderate (Le 2026 large-sample Kalshi/Polymarket study)**

The Le (2026) paper documents a strong "universal horizon effect": calibration slope (the FLB measure) rises monotonically from 0.99 (within one hour of resolution) to 1.32 (beyond one month), explaining 30.2% of calibration variance across 216 cells [src-decomposing-crowd-wisdom-domain-specific]. A slope above 1.0 indicates the market compresses probabilities toward 50% — implying that far-from-expiry contracts are more mispriced than near-expiry ones.

The proposed mechanism is uncertainty resolution and liquidity migration: as resolution approaches, informed traders move in, prices correct toward true probabilities, and calibration improves [src-decomposing-crowd-wisdom-domain-specific]. On Kalshi, large trades (>100 contracts) in politics markets show a slope of 1.74 versus 1.19 for single-contract trades (Δ = +0.53, 95% CI: 0.29, 0.75) — a trade-size scale effect not replicated on Polymarket [src-decomposing-crowd-wisdom-domain-specific], suggesting Kalshi's microstructure produces distinctive informed-trading dynamics.

**Fee survivability:** Not computed in the Le paper; gross edge from the horizon effect is implied but not quantified as a per-trade return [src-decomposing-crowd-wisdom-domain-specific].

---

### 1d. Thin Markets, Wide Spreads, and News-Reaction Speed

**Evidence quality: Low–Moderate (spread tiers from industry sources, half-life evidence from Le 2026 as summarized)**

Bid-ask spread tiers by market category, from FalconX/Kaiko data [src-5-cent-spreads-in-prediction-markets-liq]:
- High-volume thick markets: **1–3¢** spread
- Mid-tier markets: **3–7¢**
- Niche markets: **8–15¢**

Polymarket's average bid-ask spread narrowed from approximately **4.5% in 2023** to roughly **1.2% by late 2025**, a substantial improvement driven in part by the Liquidity Incentive Program [src-polymarket-fees-2026-calculator-complete].

On news-reaction speed: Le (2026), as summarized in the findings, reports that arbitrage-deviation half-lives fell from **hours** in early periods to **under a minute** by late 2025 [src-the-anatomy-of-a-blockchain-prediction-m]. This indicates that "slow reaction to breaking news" has largely been competed away on liquid markets.

A documented latency-arbitrage example: a wallet on Polymarket turned ~$300 into more than $400,000 in one month by exploiting a **2–10 second lag** between Bitcoin/Ethereum/Solana price moves on Binance and Polymarket's ultra-short (15-minute) crypto contracts [src-prediction-markets-are-turning-into-a-bo]. An estimated ~$40M was extracted from Polymarket by structural arbitrageurs between April 2024 and April 2025 [src-prediction-markets-are-turning-into-a-bo].

Thin-market edges are documented qualitatively, but thin order books (depth <$5,000) are also described as "destroying edges" for market makers attempting to provide liquidity in low-activity markets [src-how-to-build-a-prediction-market-trading].

**What requires proprietary order-book data:** Exact spread distributions by market category and probability level; fill-rate curves for resting limit orders; queue-position dynamics; precise latency distributions from specific geographic locations.

---

### 1e. Correlated-Market Inconsistencies (Mutually Exclusive Contracts)

**Evidence quality: Moderate (academic paper + NYT investigation)**

Saguillo et al. (arXiv, August 2025) analyzed 100,000+ events across ten prediction-market venues from 2018 to 2025 and found that approximately **6% of events are concurrently listed** across platforms, with semantically equivalent contracts exhibiting persistent execution-aware price deviations of **2–4% on average** even in liquid settings [src-semantic-non-fungibility-and-violations]. These deviations persist due to "structural frictions rather than informational disagreement" — the paper terms this "semantic non-fungibility" [src-semantic-non-fungibility-and-violations].

A within-platform example: a three-way mutually exclusive election contract with probabilities at $0.38 + $0.33 + $0.27 = $0.98 provides a 2.04% gross edge. After a 1.5% assumed fee, the net shrinks to 0.54% — illustrating extreme fee sensitivity for small within-platform arbs [src-the-microstructure-of-wealth-transfer-in].

Structural arbitrageurs have extracted approximately **$40M from Polymarket** in one year (April 2024–April 2025) via combinatorial and structural pricing inefficiencies [src-prediction-markets-are-turning-into-a-bo].

---

## Facet 2: Cross-Platform Arbitrage

### 2a. Documented Cases and Price-Gap Magnitudes

The best-documented case is a June 2026 NYT investigation: in March 2026, Kalshi priced Gavin Newsom's 2028 Democratic nomination at 29¢ while Polymarket priced it at 24¢. Buying YES on Polymarket (24¢) and NO on Kalshi (71¢) cost 95¢ total for a guaranteed $1 payout — a ~5 percentage-point spread yielding approximately **3% net profit** after Kalshi's transaction fee. This opportunity **persisted unexploited for weeks** [src-you-can-make-free-money-on-polymarket-if].

A practitioner source documents a worked sports example: Kalshi YES at 42¢, Polymarket NO at 53¢ on the same event = total cost $0.95 vs. $1.00 guaranteed payout → **5.3% gross edge before fees** [src-polymarket-kalshi-trading-bot-automate-p]. One practitioner (Ryan Noel) is reported to make 1,000+ arbitrage bets per week across sports markets, netting over $1M total, with typical edge shrinking from 8% to 4–5% by 2026 and opportunity windows collapsing from 30 seconds to 2–5 seconds [src-you-can-make-free-money-on-polymarket-if].

The academic paper [src-semantic-non-fungibility-and-violations] finds 2–4% average persistent deviations across 100,000+ events — the strongest systematic evidence of the structural size of cross-platform gaps.

### 2b. Settlement-Rule Mismatches: The Central Risk

Settlement-rule mismatches between "the same" contract on Kalshi vs. Polymarket represent the single largest risk factor for cross-platform arbitrage [src-how-kalshi-and-polymarket-settle-event-c]. Documented divergence categories:

- **Different deadlines and definitions** — announcement date vs. effective date; "bill passing" vs. "signed" vs. "enacted" [src-prediction-market-settlement-rules-avoid].
- **Different resolution mechanisms** — Kalshi uses a CFTC-certified internal markets team; Polymarket uses UMA's Optimistic Oracle, which is permissionless and on-chain [src-how-kalshi-and-polymarket-settle-event-c][src-polymarket-vs-kalshi-how-the-world-s-two].

**Documented divergence incidents:**

- **Cardi B Super Bowl Halftime (February 2026):** Kalshi invoked Rule 6.3(c) (unresolvable outcome) and settled at last traded price ($0.26 YES); Polymarket resolved YES at $1.00. Volume: $47.3M on Kalshi, $10M+ on Polymarket. An arbitrageur positioned in opposite directions on the two platforms would have faced catastrophic asymmetric settlement [src-how-kalshi-and-polymarket-settle-event-c].
- **Ukraine rare-earth-minerals deal (March 2025):** $7M+ volume on Polymarket; a single UMA token holder controlling ~25% of the vote resolved YES despite no confirmed deal [src-how-kalshi-and-polymarket-settle-event-c].
- **Venezuela invasion (January 2026):** $10.5M+, resolved NO but payouts were withheld [src-how-kalshi-and-polymarket-settle-event-c].
- **Zelenskyy suit market:** ~$14M, reversed to NO after a UMA vote [src-how-kalshi-and-polymarket-settle-event-c].
- **Kalshi Iran Supreme Leader market:** Kalshi refused to pay out $77M in winnings [src-polymarket-vs-kalshi-how-the-world-s-two].

Kalshi has no formal arbitration mechanism — the documented practitioner recourse is informal public pressure [src-how-kalshi-and-polymarket-settle-event-c]. A $750 USDC bond is required to escalate a Polymarket dispute via UMA [src-how-kalshi-and-polymarket-settle-event-c].

### 2c. Fee Differentials

**Kalshi fees** (adjudicated standard formula [src-kalshi-fees-how-much-does-kalshi-charge]):
- Taker fee: 0.07 × C × P × (1−P) per contract
- Maker fee: 0.0175 × C × P × (1−P); reimbursed monthly if total exceeds $10
- Maximum taker fee at p=0.50, 100 shares = $1.75

**Polymarket fees** (official documentation [src-trading-fees-on-polymarket]):
- Maker fee: **0%** (limit orders that add liquidity pay nothing)
- Taker fee by category: Geopolitics **0%**, Sports **0.03%**, Finance/Politics **0.04%**, Crypto **0.07%**
- Maker Rebates Program: redistributes approximately 20–25% of taker fees to makers [src-trading-fees-on-polymarket]

**Additional Polymarket costs:** Gas on Polygon (~$0.001–$0.01 per trade) plus third-party fiat on-ramp fees [src-kalshi-vs-polymarket-a-side-by-side-comp]. Kalshi charges 2% on debit card deposits (ACH is free) [src-card-deposits].

**Note on a contradictory fee claim:** One commercial vendor source (Claw Arbs) reports a tiered profit-based Kalshi fee schedule (7% of profit under $50K monthly volume, tapering to 1% above $1M) [src-kalshi-vs-polymarket-how-to-arbitrage-pr]. This is inconsistent with the adjudicated per-contract formula. The standard formula is treated as authoritative; the vendor claim is flagged as low-credibility and unverified.

### 2d. Capital Lockup and Transfer Latency

Both platforms require capital to remain locked until contract resolution [src-polymarket-kalshi-trading-bot-automate-p]. A $100 position on a 30-day contract ties up $100 for that period, imposing an opportunity cost of approximately 0.41% at a 5% annual rate.

**Kalshi settlement:** Within a few hours after resolution by the internal markets team [src-how-kalshi-and-polymarket-settle-event-c]. **ACH withdrawal:** Free, median ~18 hours (documented across five live withdrawals) [src-kalshi-review-june-2026-real-money-test]. Wire withdrawal: $25 outbound fee, ~26 hours [src-kalshi-review-june-2026-real-money-test].

**Polymarket settlement:** 2-hour challenge period if uncontested (~98.5% of markets); 48–96 hours if escalated to DVM vote; disputed ~2% of markets can lock funds for 4–7 days [src-how-kalshi-and-polymarket-settle-event-c][src-polymarket-vs-kalshi-how-the-world-s-two]. Settlement is on-chain in USDC on Polygon.

**Settlement-currency mismatch:** Kalshi settles in USD via ACH to US bank accounts; Polymarket settles in USDC on Polygon. Any cross-platform profit repatriation requires currency conversion and bridging — a friction invisible to simple spread calculations [src-kalshi-vs-polymarket-operator-affiliate].

### 2e. Geographic Impossibility of Simultaneous Operation

The most consequential practical constraint: **no single trader can legally operate on both Kalshi and Polymarket simultaneously.** The definitive access matrix:

| Trader class | Kalshi API | Polymarket Global API | Polymarket US API |
|---|---|---|---|
| **US person** | YES (SSN required, US bank for ACH, legally accessible as CFTC-regulated DCM) [src-is-polymarket-legal-in-the-usa-2026-upda] | **NO** — illegal per 2022 CFTC settlement; ToS explicitly prohibits US persons; the developer repository explicitly extends this prohibition to API/agents [src-polymarket-agents][src-is-polymarket-legal-in-2026] | **NO** — CFTC-approved entity (QCX LLC) is iOS-only as of mid-2026, no documented programmatic API endpoint [src-health-api-overview-polymarket-us-docume][src-what-is-polymarket-us] |
| **Non-US person** | **NO** — requires US SSN for identity verification and US bank account for ACH [src-is-polymarket-legal-in-the-usa-2026-upda][src-bank-deposits] | YES (from non-restricted jurisdictions) [src-is-polymarket-legal-in-2026] | Not designed for non-US persons |

**Conclusion:** Cross-platform arbitrage between Kalshi and Polymarket Global requires two separate traders in different jurisdictions — adding counterparty risk, settlement-timing mismatch, and legal complexity not present in single-entity arbitrage. It is **not a standalone scalable strategy** for any single operator.

Additionally, at least 11 US states have issued cease-and-desist orders against Polymarket US; Minnesota enacted an outright ban (effective August 1, 2026); Nevada has a court-ordered ban; and the CFTC has sued multiple states [src-is-polymarket-legal-in-2026]. Even US persons legally authorized to use Polymarket US may be restricted depending on their state.

---

## Facet 3: Market-Making and Liquidity Provision

### 3a. Fee Structures and Rebate Programs

**Kalshi makers:** Fee = 0.0175 × C × P × (1−P); reimbursed monthly if aggregate exceeds $10, effectively zeroing maker fees for active traders [src-kalshi-fees-how-much-does-kalshi-charge]. No documented separate maker rebate program beyond this reimbursement.

**Polymarket Global makers:** Maker fee is **0%** for all limit orders that add liquidity [src-trading-fees-on-polymarket]. The Maker Rebates Program redistributes approximately 20–25% of collected taker fees back to makers [src-trading-fees-on-polymarket].

**Polymarket's Liquidity Incentive Program (LIP) — Active as of July 2026** [src-liquidity-rewards-polymarket-documentati][src-liquidity-rewards]:

The LIP pays users for placing resting limit orders that narrow the spread and add depth. Scoring formula: S(v,s) = ((v−s)/v)² × b, where v = maximum spread from midpoint, s = order's distance from midpoint, b = order size. Rewards are allocated proportionally via random snapshots every second. Key design features:

- **Two-sided quoting is strongly incentivized:** Single-sided quoting earns 1/3 the score when midpoint is 0.10–0.90, and zero outside [0.10, 0.90] [src-liquidity-rewards-polymarket-documentati].
- **Daily reward pools** by category: Politics $250/day/event, ATP/WTA winner futures $500/day, Wimbledon $2,500/draw/day, Climate $1,000/day, Macro $250/day, Culture $250/day [src-liquidity-incentive-program-polymarket-u].
- **World Cup 2026 escalating caps:** Group Stage $6,110/game, Round of 16 $18,200/game, Final $52,000/game [src-liquidity-rewards-polymarket-documentati].
- **Minimum payout threshold:** $1/day — days below $1 earn nothing and do not roll over [src-liquidity-rewards].
- **NBA Playoffs:** $103,500 per game; PGA Tour: $150,000 per tournament [src-liquidity-incentive-program-polymarket-u].

**Polymarket US (QCX LLC):** Flat structure — taker fee 0.30%, maker rebate **+0.20%** (minimum $0.001 per trade) [src-polymarket-fees-2026-calculator-complete]. This is a distinct entity from Polymarket Global, accessible only through its iOS app as of mid-2026, with no documented programmatic trading API.

### 3b. Becker (2026) Maker Excess Return

Becker (2026) documents that Kalshi makers earned a gross excess return of **+1.12%** (95% CI +1.11% to +1.13%) [src-the-microstructure-of-wealth-transfer-in]. This is the most precisely estimated quantitative edge in the evidence base. Category heterogeneity is substantial: Finance markets show only a 0.17 percentage-point maker-taker gap (near-perfect efficiency); Sports shows 2.23 pp; World Events shows 7.32 pp [src-the-microstructure-of-wealth-transfer-in-2].

**Critical caveat:** This is a gross return only. The paper explicitly does not apply Kalshi's fee schedule and cannot be used to claim market-making is net profitable [src-the-microstructure-of-wealth-transfer-in-2].

A separate research finding (Yang, March 2026, analyzed across 150M Polymarket trades) reports that **skill, not maker/taker role, determines profitability**: skilled traders (top 5% by accuracy) earn $121 as makers and $63 as takers per market; ordinary traders lose on both sides [src-research-review-24-april-2026-prediction]. This challenges the assumption that simply providing liquidity earns a reliable spread.

### 3c. Adverse-Selection Risk

The Stanford Law adverse-selection study [src-adverse-selection-in-prediction-markets] finds that **one-sided order flow predicts maker losses** specifically in single-name (event-concentrated) Kalshi markets, using an adaptation of the VPIN (Volume-Synchronized Probability of Informed Trading) metric. Market makers face systematically higher informed-trading risk in concentrated markets, though wider spreads partially compensate.

A Stanford MSE project (2026) independently developed a burst-detection algorithm for prediction-market adverse selection [src-when-should-a-market-maker-refuse-a-bet]: flagged (potentially informed) trades were associated with "significantly larger subsequent price movements than unflagged trades," confirming adverse selection is detectable. However, the model requires market-specific calibration — "a model tuned for one market could perform poorly in another" [src-when-should-a-market-maker-refuse-a-bet]. **No quantitative estimate of the dollar magnitude of adverse-selection losses is available in any source.**

### 3d. Breakeven Thresholds for Makers vs. Takers

From the synthesized breakeven computation (q-042-c35 finding) using adjudicated fee rates and FalconX/Kaiko spread tiers [src-5-cent-spreads-in-prediction-markets-liq]:

| Strategy | p=0.10 | p=0.50 | p=0.90 |
|---|---|---|---|
| Kalshi Maker | ≥0.6%* | ≥0.9%* | ≥0.6%* |
| Kalshi Taker | ≥3.5% | ≥3.7% | ≥3.5% |
| Polymarket Maker | negative** | negative** | negative** |
| Polymarket Taker (Crypto) | ≥2.9% | ≥1.9% | ≥2.9% |
| Polymarket Taker (Geopolitics) | ≥2.9% | ≥1.9% | ≥2.9% |

*Kalshi maker breakeven is before subtracting spread-capture revenue, which at mid-tier spreads (1.5–2.5¢/side) makes the net cost negative in practice — spread capture alone exceeds fee + lockup costs for active makers.

**Polymarket maker net cost is negative due to 0% maker fee + spread capture (1.5–2.5¢/side); gas ($0.0002/share) and capital lockup ($0.0041/share) are dwarfed. The binding constraint is adverse selection, not explicit costs [src-5-cent-spreads-in-prediction-markets-liq].

---

## Facet 4: Bot Architecture on Each Platform

### 4a. Kalshi API

**Authentication:** RSA-PSS signatures using three HTTP headers on every request: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, and `KALSHI-ACCESS-TIMESTAMP` [src-get-balance][src-get-perps-account-api-limits]. Earlier sources described a Bearer token flow with 30-minute expiry [src-kalshi-api-the-complete-developer-s-guid]; this reflects the deprecated v1 API. The current v2 API uses RSA-PSS exclusively.

**Rate limits:** Token-bucket model with separate read and write buckets [src-rate-limits-and-tiers][src-get-perps-account-api-limits]. Default cost is 10 tokens per request; balance endpoint costs 5 or 50 tokens depending on parameter [src-get-balance]. Tiers by tokens/second (Read/Write): Basic (200/100), Advanced (300/300), Expert (600/600), Premier (1000/1000), Paragon (2000/2000), Prime (4000/4000), Prestige (6000/8000) [src-rate-limits-and-tiers]. Tier qualification is volume-based (Expert requires ≥0.075% trailing 30-day volume share) [src-rate-limits-and-tiers]. Rejected requests return HTTP 429 with no `Retry-After` header [src-rate-limits-and-tiers].

**Supported order types** (REST, v2 event-market endpoint `POST /trade-api/v2/portfolio/events/orders`) [src-create-order-v2-kalshi-api-documentation]:
- `fill_or_kill` (FOK)
- `good_till_canceled` (GTC; with optional `expiration_time` for de facto GTD behavior)
- `immediate_or_cancel` (IOC)
- Market orders, stop orders, and stop-limit orders are **not supported**

**Order parameters include:** `ticker`, `side` (bid/ask), `count`, `price`, `post_only` (boolean), `reduce_only` (boolean — requires IOC or FOK), `self_trade_prevention_type` (taker_at_cross or maker), `client_order_id`, `cancel_order_on_pause`, `expiration_time`, `subaccount`, `order_group_id` [src-create-order-v2-kalshi-api-documentation][src-create-order-kalshi-api-documentation]. Minimum order sizes are **not documented**.

**Market-data feeds:**
- **REST API:** Production base `https://api.kalshi.com/v1` (or `trade-api/v2` for v2 endpoints) [src-kalshi-api-the-complete-developer-s-guid]
- **FIX Market Data Session:** Host `marketdata.fix.elections.kalshi.com`, port 8233, TargetCompID `KalshiMD`; supports order-book snapshots, incremental updates, trade entries, and trading-status changes [src-market-data-kalshi-api-documentation][src-connectivity-kalshi-fix-api-documentatio]
- **WebSocket:** Real-time market updates; requires authentication [src-best-prediction-market-apis-for-develope]
- FIX feed does not support message retransmission [src-market-data-kalshi-api-documentation]
- FIX Mass Cancel limited to 1 request/second [src-connectivity-kalshi-fix-api-documentatio]

**FIX Execution Reports:** Kalshi's FIX API for margin/perpetual products returns actual fee dollar amounts on fills via proprietary tags: tag 136 (NoMiscFees), tag 137 (MiscFeeAmt — total fee in dollars, signed negative), tag 138 (MiscFeeCurr — USD), tag 139 (MiscFeeType — "Exchange fees") [src-fix-order-entry-kalshi-api-documentation]. Standard FIX commission fields (Tags 12/13) are not used. Whether the event-contract FIX API uses the same schema is not confirmed.

**Sandbox/demo environment:** Available at `https://external-api.demo.kalshi.co/trade-api/v2` (REST) and `fix.demo.kalshi.co`/`marketdata.fix.demo.kalshi.co` (FIX), using the same ports and TargetCompIDs as production [src-get-balance][src-connectivity-kalshi-fix-api-documentatio]. Demo credentials require mock SSN/address info; mock funds available via test Visa/Mastercard numbers, Plaid sandbox, or testnet crypto [src-creating-and-using-a-demo-account].

**Official SDKs:** Three maintained packages — `kalshi_python_sync`, `kalshi_python_async`, and a TypeScript SDK — all include RSA-PSS signing, type-safe models, and error handling. The older `kalshi-python` is deprecated [src-best-prediction-market-apis-for-develope]. Community SDKs include a Go SDK at `github.com/ammario/kalshi` and `KalshiCliAPI` on PyPI [src-best-prediction-market-apis-for-develope].

**Community bot maturity:** GitHub repos in categories: API wrappers, price scrapers, threshold bots ("buy YES at $0.30, sell at $0.50"), signal-based bots, and cross-platform arb bots [src-best-kalshi-trading-bots-on-github-2026]. These are characterized as "proof-of-concept" with poor error handling, no rate-limit awareness, untested with real capital, and no risk management [src-best-kalshi-trading-bots-on-github-2026]. No open-source bot with disclosed production P&L was found.

**Kalshi fee schedule PDF:** An archived copy exists on the Wayback Machine (July 8, 2025 snapshot titled "Fee Schedule for July 2025 — 7.8.25 Update"), confirming the document exists [src-fee-schedule-for-july-2025-7-8-25-update]. However, the PDF's text content streams could not be extracted (compressed/image-encoded); the actual fee figures remain inaccessible through this path.

### 4b. Polymarket CLOB API

**Architecture:** Hybrid-decentralized — off-chain CLOB matching engine with on-chain settlement via an audited Exchange contract on Polygon (chain ID 137). Orders are EIP-712 signed messages; matched trades settle atomically on-chain. The operator cannot execute unauthorized trades [src-trading-on-the-polymarket-clob].

**Authentication:**
- **L1 (credential derivation):** EIP-712 signature over a structured message yields API credentials. Required REST headers: `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_NONCE` [src-trading-on-the-polymarket-clob].
- **L2 (trading operations):** HMAC-SHA256 signing. Required headers: `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_API_KEY`, `POLY_PASSPHRASE`. Order creation additionally requires the private key for EIP-712 signing [src-trading-on-the-polymarket-clob].
- Credentials derived from wallet private key using `create_or_derive_api_creds()` [src-polymarket-py-clob-client].

**API host:** `https://clob.polymarket.com` [src-trading-on-the-polymarket-clob].

**Rate limits:** Not documented in official sources [src-polymarket-py-clob-client][src-order-entry-management-and-best-practice].

**Supported order types** [src-order-entry-management-and-best-practice]:
- **GTC** (Good-Til-Cancelled) — default for passive quoting
- **GTD** (Good-Til-Date) — auto-expires at specified time; recommended for pre-event quote withdrawal
- **FOK** (Fill-Or-Kill) — full fill or cancellation; used for aggressive rebalancing
- **FAK** (Fill-And-Kill / partial FOK) — fills available quantity, cancels remainder
- Batch ordering: up to **15 orders per request** via `postOrders()` [src-order-entry-management-and-best-practice]

**Wallet types:** EOA (ID 0), POLY_PROXY (ID 1), GNOSIS_SAFE (ID 2), POLY_1271 (ID 3 — recommended for new API users) [src-trading-on-the-polymarket-clob].

**USDC approvals required once per wallet** for: USDC (Polygon: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`) and Conditional Tokens (`0x4D97DCd97eC945f40cF65F87097ACe5EA0476215`), both approved for three contracts (main exchange, neg risk markets, neg risk adapter) [src-polymarket-py-clob-client].

**Matching engine location:** eu-west-2 (primary), eu-west-1 (secondary). Direct co-location available for KYC/KYB users [src-trading-on-the-polymarket-clob]. No numerical latency benchmarks are documented.

**Gas costs:** Estimated at $0.001–$0.01 per trade on Polygon (actual variability with network congestion unquantified) [src-how-to-build-a-prediction-market-trading].

**SDK status:**
- **py-clob-client (Python):** ARCHIVED May 25, 2026; explicitly "no longer maintained" and "no longer functional." Users directed to `github.com/Polymarket/py-sdk` [src-polymarket-py-clob-client]. Had 1.2k stars, 391 forks before archiving.
- **Replacement SDK:** `py-sdk` and `@polymarket/clob-client-v2` (TypeScript) and `polymarket_client_sdk_v2` (Rust) are referenced in current docs but no maturity or maintenance assessment is provided [src-order-entry-management-and-best-practice][src-polymarket-py-clob-client].
- The clob-client repository itself is separately maintained at `github.com/Polymarket/clob-client` [src-clob-client].

**Geoblocking and US access:** The CLOB API at clob.polymarket.com enforces IP-based geoblocking for US persons. Polymarket's official developer repository for AI agents explicitly states US persons are prohibited from trading "via UI & API and including agents developed by persons in restricted jurisdictions" [src-polymarket-agents]. VPN circumvention violates Terms of Service Section 2.1.4 and risks account and fund freezes [src-is-polymarket-legal-in-2026].

**Polymarket US (QCX LLC) API:** As of mid-2026, the only documented endpoint for Polymarket US's programmatic infrastructure is a health check at `GET /v1/health` returning `{"status": "SERVING"}` [src-health-api-overview-polymarket-us-docume]. No trading API reference is published. The platform's intermediated structure may require FCM broker intermediation for any programmatic access, but this is unconfirmed [src-polymarket-receives-cftc-approval-of-ame].

---

## Facet 5: What "Reproducible Profitable" Actually Requires

### 5a. Edge-vs-Breakeven Comparison (Adjudicated Standard Kalshi Fee)

Using the adjudicated standard Kalshi fee and the computed breakeven thresholds:

**FLB strategy (taker, buying contracts >50¢ on Kalshi):**
- Gross edge: approximately 1.5–2.4% per secondary synthesis [src-favorite-longshot-bias]; Bürgi et al. finds "small positive returns" above 50¢ but overall −22% after fees [src-what-five-new-academic-papers-say-about].
- Breakeven for Kalshi taker at p=0.90: ≥3.5%.
- **Does NOT clear** the taker breakeven. The binding constraint is the 0.07 × P × (1−P) taker fee plus spread-crossing cost. A 1.5–2.4% gross edge on a taker position at p=0.90 (fee ≈ $0.63/100 shares + half-spread) is consumed.

**FLB strategy (maker, providing liquidity on high-probability contracts):**
- Becker gross maker return: +1.12% [src-the-microstructure-of-wealth-transfer-in].
- Kalshi maker breakeven: ≈0.6–0.9% before spread capture; spread capture of 1.5–2.5¢/side makes net cost negative for active makers.
- **May clear** the Kalshi maker breakeven — the gross edge exceeds the fee+lockup cost, and spread capture adds further income. However, adverse selection is not costed; the binding constraint shifts to adverse selection magnitude (unquantified) and fill rates (unquantified).

**Calibration/YES-NO asymmetry (NO side at low prices, maker on Kalshi):**
- Gross excess return at 1¢: makers earn +1.57% gross [src-the-microstructure-of-wealth-transfer-in]. Maker fee at p=0.01: 0.0175 × 0.01 × 0.99 = $0.000173/share — negligible. Spread capture at p=0.01 likely tiny. Lockup cost: 0.41%.
- **Clears** fee-based breakeven easily for makers on extreme-probability contracts. But the practical constraint is that such markets have thin books — depth at 1¢ is minimal — and fill rates for resting limit orders here are unknown. The entire $18.26B volume in Becker's sample was dominated by more liquid price levels.

**Cross-platform arb (~3% net, NYT Newsom example):**
- Gross/net: ~3% net documented in one example [src-you-can-make-free-money-on-polymarket-if].
- **Clears** both platform fee thresholds on the face of it — but this is **structurally unavailable** to any single trader class as of mid-2026 (US persons blocked from Polymarket Global API; non-US persons blocked from Kalshi).
- Even ignoring the geographic constraint: settlement-rule mismatch risk (demonstrated by the Cardi B incident) makes the "guaranteed" payout non-guaranteed. The expected loss from the ~2% disputed-outcome rate is not small [src-how-kalshi-and-polymarket-settle-event-c].

**Polymarket maker + LIP strategy:**
- Maker fee: 0%; breakeven: negative (spread capture dwarfs gas + lockup) [src-5-cent-spreads-in-prediction-markets-liq].
- LIP rewards provide additional income — quadratic scoring, daily pools, World Cup caps [src-liquidity-rewards-polymarket-documentati].
- **In principle clears breakeven from explicit costs alone.** The binding constraint is adverse selection: informed traders around news events pick off resting quotes. The Stanford adverse-selection finding [src-adverse-selection-in-prediction-markets] confirms this risk is real and material in single-name markets, but the magnitude is unquantified.

### 5b. Maximum Plausible Annual Return

For a US retail trader deploying $10,000–$50,000 on Kalshi alone (since Polymarket Global is inaccessible to US persons) with a maker-only posture targeting high-probability politics/sports contracts:

- Gross maker edge: +1.12% per Becker [src-the-microstructure-of-wealth-transfer-in], achieved by providing liquidity on both sides
- Explicit costs (fee + lockup): ~0.85% at p=0.50, near-zero at extreme probabilities; largely offset by spread capture
- Unknown costs: adverse selection around news events, fill rate below 100%, queue position effects, capital not always deployed

A **speculative, unverified upper bound** for net annual return on a maker-only Kalshi strategy: 2–5% on deployed capital, heavily dependent on market category (sports >> finance per Becker's category decomposition), fill rates, and adverse-selection magnitude. This range is the synthesizer's inference from available partial data — **no primary source documents an annualized net return figure.**

For a non-US trader deploying $10,000–$50,000 as a maker on Polymarket Global with LIP participation:
- Maker fee: 0%; spread capture positive; LIP rewards additive but highly variable with reward pool competition
- Adverse selection: real and unquantified [src-when-should-a-market-maker-refuse-a-bet]
- **Same caveats; no primary source documents a net return figure.**

The $35-to-$2M AI trajectory on Kalshi reported by one practitioner is documented as explicitly non-reproducible ("cannot repeat that — there's only so much easy money, and his AI had already taken it all") [src-the-ai-superforecasters-are-here]. The $300-to-$400K in one month latency-arb example is an extreme outlier on ultra-short crypto contracts — a now heavily competed edge [src-prediction-markets-are-turning-into-a-bo].

### 5c. Unquantified Cost Categories

The following costs are **not quantified in any source reviewed** and therefore cannot be incorporated into the breakeven analysis:

1. **Adverse-selection magnitude around news events** — qualitatively confirmed to be real [src-adverse-selection-in-prediction-markets][src-when-should-a-market-maker-refuse-a-bet]; dollar magnitude unknown.
2. **Fill rates for resting limit orders** — at what fraction of theoretical gross edge does a maker actually get filled (vs. being left at the back of queue)?
3. **Queue position dynamics** — time priority in a FIFO queue; first-in makers have dramatically different economics than later arrivals.
4. **Polymarket gas cost variability** — estimated at $0.001–$0.01 per trade [src-how-to-build-a-prediction-market-trading] with unknown congestion variance.
5. **Settlement-risk premium** — the expected value cost of disputed resolutions (Cardi B, Ukraine, Venezuela incidents) [src-how-kalshi-and-polymarket-settle-event-c].
6. **Withdrawal/deposit friction for non-ACH methods** — debit card deposit fee 2% per official Kalshi documentation [src-card-deposits]; wire withdrawal $25 [src-kalshi-review-june-2026-real-money-test].
7. **Slippage on large orders** — acknowledged qualitatively as a hidden cost [src-polymarket-fees-2026-calculator-complete] but not quantified.

### 5d. Central Negative Finding

**No published source documents a fully-costed net-profitable prediction-market trading strategy.** The strongest available statement on net returns comes from Bürgi et al. (2026), which reportedly finds −22% after fees — a net loss — across the population of Kalshi market participants [src-what-five-new-academic-papers-say-about][src-makers-and-takers-the-economics-of-the-k-2]. Becker (2026) provides only gross returns and explicitly does not apply the fee schedule [src-the-microstructure-of-wealth-transfer-in-2]. All other quantitative return claims in the evidence base are either promotional, survivorship-biased, gross of major cost categories, or from individual extreme-outlier trajectories.

Confirming the scale of the challenge: only **7–8% of Polymarket wallets** consistently generate profits [src-prediction-markets-are-turning-into-a-bo]; the top 5% of traders by accuracy extract $228M over three years — implying exceptional, non-replicable skill rather than mechanical edge exploitation [src-research-review-24-april-2026-prediction].

---

## Facet 6: Legal, Regulatory, and ToS Constraints

### 6a. Kalshi Regulatory Status and CFTC Implications

Kalshi (KalshiEx LLC) is a CFTC-designated contract market (DCM) since 2020 [src-how-courts-and-regulators-are-redefining]. API-based automated trading is implicitly permitted — Kalshi's own documentation provides FIX protocol support, WebSocket feeds, and tiered API rate limits designed for high-frequency automated access [src-rate-limits-and-tiers][src-connectivity-kalshi-fix-api-documentatio]. No documentation reviewed explicitly prohibits bot trading; the tier system suggests it is expected and accommodated.

**Regulatory risk for automated traders:** In April 2026, Kalshi published three disciplinary notices under Rule 5.17(z) prohibiting "decision makers" from trading on their own races, imposing 5-year suspensions and fines [src-cftc-and-kalshi-announce-enforcement-act]. While targeted at self-interested decision makers, this demonstrates active enforcement capability applicable to any trader with material nonpublic information.

**State preemption litigation:** The CFTC sued Arizona, Connecticut, and Illinois in April 2026 to prevent state interference with federally regulated event markets [src-how-courts-and-regulators-are-redefining]. The Third Circuit affirmed a preliminary injunction for Kalshi against New Jersey; state regulators prevailed at the preliminary-injunction stage in Nevada, Maryland, and Ohio [src-how-courts-and-regulators-are-redefining]. This regulatory flux creates geographic access uncertainty even for US persons on Kalshi.

**CFTC Rule 180.1:** Academic analysis (Mitts & Ofi, March 2026) argues CFTC Rule 180.1 (anti-fraud on event contracts) is narrower than SEC Rule 10b-5, creating a regulatory gap for informed trading on prediction markets [src-research-review-24-april-2026-prediction]. Flagged traders in that analysis showed a 69.9% win rate with ~$143M aggregate anomalous profit identified — indicating the enforcement gap is being actively exploited [src-research-review-24-april-2026-prediction].

**CFTC AI/bot ANPR:** In March 2026, the CFTC issued an Advance Notice of Proposed Rulemaking on autonomous AI trading on event contracts [src-ai-prediction-market-case-studies-6-impl] — signaling potential future restrictions.

### 6b. Polymarket Jurisdiction Restrictions

Polymarket (Blockratize Inc.) settled with the CFTC in January 2022 for **$1.4 million**, charged with operating an unregistered facility trading event-based binary options without CFTC approval [src-cftc-orders-event-based-binary-options-m]. The settlement required geofencing US users, blocking US IP addresses, implementing identity verification, and maintaining compliance records [src-is-polymarket-legal-in-the-usa-2026-upda].

**Post-2022 developments:** In November 2025, the CFTC issued an Amended Order of Designation permitting Polymarket US (QCX LLC) to operate an intermediated trading platform subject to full DCM requirements [src-polymarket-receives-cftc-approval-of-ame]. This entity launched via iOS app in December 2025; the waitlist was removed around May 13–14, 2026 [src-is-polymarket-legal-in-the-us-yes-open-o]. Polymarket US's cumulative volume was approximately $700M as of mid-2026 [src-is-polymarket-legal-in-the-us-yes-open-o].

**The main international Polymarket platform (polymarket.com, API at clob.polymarket.com) remains geoblocked for US persons.** The developer repository explicitly states: "US persons and persons from certain other jurisdictions" are prohibited from trading "via UI & API and including agents developed by persons in restricted jurisdictions" [src-polymarket-agents]. This confirms the prohibition applies to automated API-based access, not just manual UI trading.

**CFTC first-ever insider trading case on prediction markets:** In April 2026, the CFTC filed a complaint against Army service member Gannon Ken Van Dyke for using classified military intelligence to trade Polymarket contracts, realizing $404,000+ in profit. CFTC Chairman Selig stated a "zero tolerance" policy [src-cftc-and-kalshi-announce-enforcement-act]. Parallel criminal charges were filed by SDNY.

### 6c. ToS Position on Automated Trading

**Kalshi ToS:** The legal Terms of Service pages at kalshi.com/terms were inaccessible despite multiple retrieval attempts during this research run. Kalshi's API documentation and rate-limit tier system [src-rate-limits-and-tiers] imply automated trading is permitted and expected, but no explicit language from the legal ToS on bot prohibitions, pre-approval requirements, or retail/institutional distinctions has been retrieved. This remains an undelivered component of Facet 6.

**Polymarket Global ToS:** The developer repository [src-polymarket-agents] explicitly prohibits US persons from API/agent access. Polymarket's ToS states: "The Services are not available to persons or entities who reside in, are located in, are incorporated in, or have a registered office in the United States of America or any Prohibited Localities" [src-is-polymarket-legal-in-the-usa-2026-upda]. However, no ToS language specifically addressing automated trading or bots (beyond the US access prohibition) was retrieved.

**Polymarket US ToS:** Not retrieved; the Polymarket US site [src-what-is-polymarket-us] references developer and API resources for "institutional participants and technology partners" but provides no ToS text.

**Documented enforcement specifically against bot operators:** No enforcement actions specifically targeting automated trading bots (as distinct from insider trading, US-access violations, or market manipulation) were found in any source reviewed.

### 6d. Summary of Legal Risk for Operators

- **US person operating on Kalshi via API:** Legally permitted; CFTC-regulated environment; subject to Rule 180.1, Kalshi's internal rule enforcement, and state-level access restrictions in Nevada and other states with cease-and-desist orders.
- **US person operating on Polymarket Global API:** Illegal per CFTC settlement; ToS violation; risk of fund freezes and account termination; VPN circumvention does not cure the legal violation and adds detection risk [src-is-polymarket-legal-in-2026].
- **Non-US person operating on Polymarket Global API:** Permitted from non-restricted jurisdictions; subject to Polymarket's geographic restrictions for approximately 30+ countries [src-polymarket-blocks-vpns-and-tightens-iden].

---

## Contradictions and Open Uncertainties

**1. Kalshi fee rate — resolved by adjudication but primary source unconfirmed.** The standard formula (maker 0.0175/taker 0.07 × C × P × (1−P)) is supported by multiple converging evidence lines including Kalshi's FIX Execution Reports returning fee amounts [src-fix-order-entry-kalshi-api-documentation], Galaxy Research independently noting fees [src-galaxy-deep-research-report-how-hyperliq], and Bürgi et al.'s finding that fees meaningfully worsen returns [src-makers-and-takers-the-economics-of-the-k-2]. However, the actual fee schedule PDF could not be text-extracted [src-fee-schedule-for-july-2025-7-8-25-update], leaving the formal adjudication as the best available estimate rather than a primary-source confirmation.

**2. Bürgi et al. −22% figure requires primary-paper verification.** The −20% before fees / −22% after fees figures are reported in a Substack newsletter summary [src-what-five-new-academic-papers-say-about], not extracted from the primary paper. The Bürgi et al. abstract confirms that fee adjustment is incorporated ("win far less often than required to break even after fees") [src-makers-and-takers-the-economics-of-the-k] but does not quote the specific percentages. The GWU PDF was hard-blocked in retrieval attempts. The specific numbers need primary-paper verification.

**3. YES/NO asymmetry consistency.** The finding that at 1¢ the YES contract has −41% expected value while the complementary NO has +23% EV was flagged for internal consistency review (since for complementary binary contracts, the relationship between YES and NO returns follows a specific mathematical constraint). This review was tasked but its finding is not among the findings provided.

**4. Kalshi overround claim — resolved by adjudication as uncorroborated.** The "110–140% combined YES+NO price" claim [src-kalshi-vs-polymarket-a-side-by-side-comp] has no corroboration from Le (2026), Becker (2026), or Galaxy Research despite all three analyzing Kalshi data in detail. It is not used in any analysis in this report and should be disregarded.

**5. Polymarket ToS and Kalshi ToS legal text — not retrieved.** Multiple attempts to access the live legal ToS pages for both platforms were blocked (HTTP 403/429). Archive snapshots and Wayback Machine alternatives were attempted but not fully resolved within the run budget. The specific legal ToS provisions on automated trading, pre-approval requirements, and enforcement remain undelivered for Facet 6.

**6. Polymarket US bot-operable API — currently unavailable.** The CFTC-approved Polymarket US entity (QCX LLC) exists and is open to eligible US users via iOS, but no programmatic trading API endpoint has been documented [src-health-api-overview-polymarket-us-docume][src-what-is-polymarket-us]. Whether API access requires FCM intermediation (as implied by the November 2025 CFTC approval structure) [src-polymarket-receives-cftc-approval-of-ame] is unconfirmed. This means US persons currently have no legal programmatic access to any prediction-market exchange other than Kalshi.

**7. Fill rates, queue dynamics, and adverse-selection magnitude.** Every profitability calculation in this report omits these costs because no source quantifies them. A market-making strategy that appears to clear the explicit-cost breakeven may be unprofitable once adverse selection and partial-fill dynamics are incorporated. Any investor seeking to deploy capital should treat the gross-edge-vs.-breakeven comparisons as necessary but insufficient conditions for profitability.

**8. Survival of the ~$40M structural arb pool.** This figure was attributed to Saguillo et al. (arXiv, August 2025) as summarized in a practitioner source [src-prediction-markets-are-turning-into-a-bo]. The primary paper was not directly retrieved and reviewed. The figure should be treated as estimated, not confirmed, from the primary source.

## Limitations & decisions

- [2026-07-06T14:26:16+00:00] routing — volume=deepseek_flash/deepseek-v4-flash, judgment=deepseek/deepseek-v4-pro, gate=anthropic/claude-opus-4-8
- [2026-07-06T14:27:27+00:00] pipeline (cycle 1): read budget 12 truncated 56 candidates -> 12 selected (dropped: 34 after-budget (unclassified), 0 domain-cap, 10 per-query-cap, 0 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T14:27:40+00:00] worker returned outcome=fragmented for q-001 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T14:27:40+00:00] worker BLOCKED on q-001 (soft, count=1): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T14:29:00+00:00] pipeline (cycle 2): read budget 12 truncated 45 candidates -> 12 selected (dropped: 19 after-budget (unclassified), 0 domain-cap, 13 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T14:29:17+00:00] worker BLOCKED on q-001 (soft, count=2): The only available source [src-a-framework-for-cross-platform-predictio] is a design/working paper that describes a framework and summarizes two other empirical studies (Ng et al. 2026, Saguillo et al. 2025), but neither the paper itself nor the summaries of those cited studies provide the specific evidence requested: systematic mispricing patterns (favorite-longshot bias, calibration errors at extreme probabilities, time-to-resolution effects), estimated edge sizes, or evidence-quality assessments for those findings. The cited studies are not directly accessible — only their findings as restated in the framework paper. No peer-reviewed results are present. The single source cannot support the breadth of the question.
- [2026-07-06T14:29:54+00:00] pipeline (cycle 3): read budget 12 truncated 79 candidates -> 12 selected (dropped: 66 after-budget (unclassified), 0 domain-cap, 1 per-query-cap, 0 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T14:31:59+00:00] pipeline (cycle 4): read budget 12 truncated 49 candidates -> 12 selected (dropped: 33 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 2 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T14:34:18+00:00] pipeline (cycle 5): read budget 12 truncated 49 candidates -> 12 selected (dropped: 34 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 2 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T14:37:34+00:00] pipeline (cycle 6): read budget 12 truncated 48 candidates -> 12 selected (dropped: 21 after-budget (unclassified), 0 domain-cap, 13 per-query-cap, 2 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T14:43:21+00:00] pipeline (cycle 8): read budget 12 truncated 37 candidates -> 12 selected (dropped: 23 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 2 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T14:46:10+00:00] pipeline (cycle 9): read budget 12 truncated 41 candidates -> 12 selected (dropped: 27 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 2 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T14:51:19+00:00] pipeline (cycle 10): read budget 12 truncated 52 candidates -> 12 selected (dropped: 26 after-budget (unclassified), 0 domain-cap, 10 per-query-cap, 0 blocked, 3 already-seen, 1 invalid)
- [2026-07-06T14:51:35+00:00] worker BLOCKED on q-012 (soft, count=1): The only available source [src-are-final-market-prices-sufficient-for-i] is a study of favorite-longshot bias in Japanese parimutuel horse-race betting. It explicitly states it does not study prediction markets, noting 'the institutional mechanism differs (no limit orders, simultaneous last-minute betting)' and that 'Transference to prediction markets is indirect and requires careful caveat.' The assigned question requires peer-reviewed empirical studies (post-2015) of favorite-longshot bias in prediction markets specifically, and this source is a preprint (not yet peer-reviewed), studies parimutuel betting (not prediction markets), and its authors caution that results do not transfer directly. A single non-conforming source cannot support the requested enumeration of multiple studies with effect sizes, sample sizes, and methodology-quality assessments.
- [2026-07-06T14:55:14+00:00] pipeline (cycle 11): read budget 12 truncated 54 candidates -> 12 selected (dropped: 31 after-budget (unclassified), 0 domain-cap, 10 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T14:59:44+00:00] pipeline (cycle 12): read budget 12 truncated 41 candidates -> 12 selected (dropped: 28 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T14:59:46+00:00] read dedup (cycle 12): https://pmc.ncbi.nlm.nih.gov/articles/PMC6778000/ carries duplicate content of already-read https://pmc.ncbi.nlm.nih.gov/articles/PMC10453007; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T14:59:57+00:00] worker BLOCKED on q-013 (soft, count=1): The single available source (a secondary blog summary of a working paper) does not contain the specific information needed to answer the assigned question. It mentions a 'Yes Bias' but provides no numerical effect sizes, no calibration error data at extreme probabilities (0-5%, 95-100%), no comparison of whether markets overstate or understate tail probabilities, no fee-adjusted edge analysis, and no evidence quality assessment for these specific claims. The source is a secondary summary with partial paywall and does not report the primary paper's numerical results. Without access to the actual working paper's data, I cannot responsibly answer any of the question's sub-components.
- [2026-07-06T15:03:36+00:00] pipeline (cycle 13): read budget 12 truncated 71 candidates -> 12 selected (dropped: 52 after-budget (unclassified), 0 domain-cap, 5 per-query-cap, 0 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T15:03:38+00:00] read dedup (cycle 13): https://pmc.ncbi.nlm.nih.gov/articles/PMC3575184/ carries duplicate content of already-read https://pmc.ncbi.nlm.nih.gov/articles/PMC10453007; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T15:08:24+00:00] evaluator (cycle 13) tried to close SEED question q-005 ('The factual constraints on simultaneous Kalshi+Polymarket operation are already documented: Kalshi is US-only KYC-gated (q-004), Polymarket ToS prohibits US persons (q-011), and settlement currency mismatch exists (q-004). The remaining question — practical feasibility — is synthetic/derivative: it will be answerable from existing findings once q-018 resolves the Polymarket US regulatory status. For international traders, the answer is structurally determined (Kalshi requires US presence, so simultaneous operation is impossible for non-US persons). The question adds no unique factual investigation beyond what q-018 + existing findings already cover. Closing as overlapping avoids duplicate effort.') — REFUSED: initializer questions are the mandated scope (blocked 0x; exhausted-scope close needs 2)
- [2026-07-06T15:08:53+00:00] pipeline (cycle 14): read budget 12 truncated 91 candidates -> 12 selected (dropped: 74 after-budget (unclassified), 0 domain-cap, 5 per-query-cap, 0 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T15:08:55+00:00] read dedup (cycle 14): https://pmc.ncbi.nlm.nih.gov/articles/PMC9344229/ carries duplicate content of already-read https://pmc.ncbi.nlm.nih.gov/articles/PMC10453007; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T15:09:01+00:00] pipeline (cycle 14): 0/12 useful reads for q-014 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T15:09:01+00:00] worker BLOCKED on q-014 (HARD, count=2): no useful reads: 12 URLs selected, 8 read but none useful, 4 fetch-failed
- [2026-07-06T15:12:47+00:00] pipeline (cycle 15): read budget 12 truncated 68 candidates -> 12 selected (dropped: 46 after-budget (unclassified), 0 domain-cap, 9 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T15:12:53+00:00] pipeline (cycle 15): 0/12 useful reads for q-014 (7 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T15:12:53+00:00] worker BLOCKED on q-014 (HARD, count=4): no useful reads: 12 URLs selected, 7 read but none useful, 5 fetch-failed
- [2026-07-06T15:16:19+00:00] evaluator (cycle 15) RETIRED q-014 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T15:16:28+00:00] pipeline (cycle 16): read budget 12 truncated 44 candidates -> 12 selected (dropped: 27 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 2 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T15:16:46+00:00] worker returned outcome=fragmented for q-015 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T15:16:47+00:00] worker BLOCKED on q-015 (soft, count=1): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T15:24:19+00:00] pipeline (cycle 17): read budget 12 truncated 45 candidates -> 12 selected (dropped: 23 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 2 blocked, 3 already-seen, 1 invalid)
- [2026-07-06T15:29:35+00:00] pipeline (cycle 18): read budget 12 truncated 39 candidates -> 12 selected (dropped: 23 after-budget (unclassified), 0 domain-cap, 3 per-query-cap, 0 blocked, 0 already-seen, 1 invalid)
- [2026-07-06T15:29:49+00:00] worker returned outcome=fragmented for q-016 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T15:29:49+00:00] worker BLOCKED on q-016 (soft, count=1): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T15:34:22+00:00] pipeline (cycle 19): read budget 12 truncated 42 candidates -> 12 selected (dropped: 28 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 0 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T15:41:06+00:00] pipeline (cycle 20): read budget 12 truncated 33 candidates -> 12 selected (dropped: 12 after-budget (unclassified), 0 domain-cap, 7 per-query-cap, 0 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T15:41:24+00:00] worker fragmented q-017 (depth 1->2) into q-032, q-033, q-034 — parent resolved without a finding
- [2026-07-06T15:45:00+00:00] evaluator (cycle 20) closed q-024 as immaterial: This question asks for time-to-resolution granularity beyond the universal horizon effect already documented in finding q-012-c11 (Le 2026: calibration slope 0.99 within 1 hour rising to 1.32 beyond 1 month, explaining 30.2% of variance). It deepens q-014 which was retired as exhausted scope after 4 hard-blocked attempts found no reachable sources. The core time-to-resolution finding is already in evidence. Additional granularity from the same papers (Le 2026, Becker 2026, Bürgi 2025) would enrich context but would not change any conclusion about edge exploitability or bot design — the horizon effect is already quantified. Closing avoids further spend on a dimension whose search space has proven barren after 8 worker cycles across q-014.
- [2026-07-06T15:45:24+00:00] pipeline (cycle 21): read budget 12 truncated 45 candidates -> 12 selected (dropped: 26 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 1 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T15:50:08+00:00] pipeline (cycle 22): read budget 12 truncated 42 candidates -> 12 selected (dropped: 25 after-budget (unclassified), 0 domain-cap, 1 per-query-cap, 2 blocked, 1 already-seen, 1 invalid)
- [2026-07-06T15:50:18+00:00] pipeline (cycle 22): 0/12 useful reads for q-021 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T15:50:18+00:00] worker BLOCKED on q-021 (HARD, count=2): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T15:53:57+00:00] pipeline (cycle 23): read budget 12 truncated 48 candidates -> 12 selected (dropped: 16 after-budget (unclassified), 0 domain-cap, 6 per-query-cap, 6 blocked, 7 already-seen, 1 invalid)
- [2026-07-06T15:54:06+00:00] pipeline (cycle 23): 0/12 useful reads for q-021 (10 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T15:54:06+00:00] worker BLOCKED on q-021 (HARD, count=4): no useful reads: 12 URLs selected, 10 read but none useful, 2 fetch-failed
- [2026-07-06T15:57:42+00:00] evaluator (cycle 23) RETIRED q-021 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T15:57:43+00:00] evaluator (cycle 23) closed q-034 as immaterial: Redundant with q-037. Both ask for the official Terms of Service from kalshi.com/terms and polymarket.com/terms regarding automated trading. q-037 is more specific (requests specific sections and paragraph numbers, distinguishes retail vs. institutional, includes polymarketexchange.com for Polymarket US) and subsumes q-034's narrower request.
- [2026-07-06T15:57:43+00:00] evaluator (cycle 23) closed q-023 as immaterial: Redundant with q-037. Both ask for ToS provisions on automated trading, bots, API usage, rate-limiting, and enforcement actions. q-037 is more comprehensive (covers all three domains — kalshi.com, polymarket.com, polymarketexchange.com — with section-level specificity) and subsumes q-023's scope.
- [2026-07-06T15:57:43+00:00] evaluator (cycle 23) closed q-033 as immaterial: Substantially answered by q-011 (finding at confidence 0.78). q-011 already documents: (a) Kalshi has been a CFTC-designated DCM since 2020, (b) Kalshi's operations are governed by CFTC rules and its own exchange rules, (c) Kalshi is the legally available CFTC-regulated venue for US persons, and (d) the existence of FIX and REST APIs with documented authentication and rate limits implies API trading is legally permitted under its DCM framework. q-015 further confirms the sandbox and production API environments. Additional CFTC.gov retrieval would enrich context but would not change any conclusion about bot-operability.
- [2026-07-06T15:57:51+00:00] pipeline (cycle 24): read budget 12 truncated 39 candidates -> 12 selected (dropped: 18 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 1 blocked, 6 already-seen, 0 invalid)
- [2026-07-06T15:58:04+00:00] worker returned outcome=fragmented for q-022 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T15:58:04+00:00] worker BLOCKED on q-022 (soft, count=1): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T16:03:59+00:00] pipeline (cycle 25): read budget 12 truncated 48 candidates -> 12 selected (dropped: 23 after-budget (unclassified), 0 domain-cap, 3 per-query-cap, 0 blocked, 10 already-seen, 0 invalid)
- [2026-07-06T16:04:14+00:00] worker returned outcome=fragmented for q-022 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T16:04:14+00:00] worker BLOCKED on q-022 (soft, count=2): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T16:08:23+00:00] pipeline (cycle 26): read budget 12 truncated 35 candidates -> 12 selected (dropped: 10 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 0 blocked, 8 already-seen, 1 invalid)
- [2026-07-06T16:08:31+00:00] pipeline (cycle 26): 0/12 useful reads for q-022 (11 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T16:08:31+00:00] worker BLOCKED on q-022 (HARD, count=4): no useful reads: 12 URLs selected, 11 read but none useful, 1 fetch-failed
- [2026-07-06T16:12:31+00:00] evaluator (cycle 26) RETIRED q-022 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T16:13:08+00:00] read dedup (cycle 27): https://docs.polymarket.com/developers/market-makers/trading carries duplicate content of already-read https://docs.polymarket.com/market-makers/trading; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T16:17:06+00:00] evaluator (cycle 27) closed q-025 as immaterial: Third-party developer resources, blog posts, and community guides for Polymarket are enrichment — they add context about developer experience but will not change any conclusion about bot feasibility, edge exploitability, or profitability. The core technical architecture for both platforms is already documented in findings q-015-c17 (Kalshi REST/FIX API) and q-016-c19 (Polymarket CLOB API). Third-party latency measurements and community bot examples, while informative, are not load-bearing for any of the six mandated facets of the research question. Closing to conserve budget for the unresolved material gaps (market-making economics, net profitability verification, fee contradiction resolution).
- [2026-07-06T16:17:16+00:00] pipeline (cycle 28): read budget 12 truncated 41 candidates -> 12 selected (dropped: 27 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 1 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T16:17:30+00:00] worker returned outcome=fragmented for q-030 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T16:17:30+00:00] worker BLOCKED on q-030 (soft, count=1): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T16:21:38+00:00] pipeline (cycle 29): read budget 12 truncated 38 candidates -> 12 selected (dropped: 21 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 2 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T16:21:52+00:00] worker returned outcome=fragmented for q-030 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T16:21:52+00:00] worker BLOCKED on q-030 (soft, count=2): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T16:25:38+00:00] evaluator (cycle 29) closed q-026 as immaterial: On-chain P&L verification via Polygon CTF Exchange contract analysis is scientifically interesting but not load-bearing for any of the six mandated facets. Even if specific bot wallets were identified and their on-chain P&L reconstructed, this would verify past performance of known wallets — it would not identify strategies, predict future profitability, estimate capacity limits, or resolve the fee contradiction. The effort required (on-chain analytics infrastructure, wallet identification, trade reconstruction) is disproportionate to the investigative value. The question q-009-c08 already flags all practitioner return claims as survivorship-biased/unverified, which is the correct treatment regardless of on-chain verification.
- [2026-07-06T16:25:38+00:00] evaluator (cycle 29) closed q-030 as immaterial: The legal prohibition on US persons using Polymarket Global's API is unambiguous from findings q-011-c09 and q-018-c21: the 2022 CFTC settlement requires geoblocking, Polymarket's ToS and developer documentation explicitly prohibit US persons from trading via API, and Polymarket Global has not lifted this restriction as of mid-2026. Whether the geoblocking is technically enforceable via IP checks or VPN detection does not change the legal conclusion — US-based bot operators cannot legally use clob.polymarket.com regardless of technical workarounds. The question is interesting for understanding enforcement mechanisms but is immaterial to the report's conclusions about what is legally permissible versus technically possible.
- [2026-07-06T16:26:10+00:00] pipeline (cycle 30): read budget 12 truncated 67 candidates -> 12 selected (dropped: 53 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 2 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T16:30:24+00:00] evaluator (cycle 30) closed q-032 as immaterial: IMMATERIAL. q-032 asks for CFTC actions, statements, or enforcement proceedings involving Polymarket since January 2022 through July 2026. The core regulatory picture is already conclusively established: (a) the January 2022 settlement ($1.4M fine, cease-and-desist, US geoblock) is documented in q-011-c09 and q-018-c21, (b) the November 2025 Amended Order of Designation enabling Polymarket US is documented in q-018-c21, and (c) the practical consequence for bot operators — US persons cannot legally use clob.polymarket.com; Polymarket US exists but its API availability is unknown — is stated in q-018-c21. Additional post-2022 CFTC press releases or docket entries would enrich regulatory context but would not change any conclusion about bot operation, edge exploitability, or legal risk assessment. The investigation has already spent multiple blocked cycles on CFTC.gov retrieval (q-022 retired exhausted after 4 hard blocks), indicating the search space is either inaccessible or barren. Closing q-032 conserves budget for the unresolved material gaps: fee-structure verification (q-038, q-043, q-046), net-profitability analysis (q-031, q-042, q-047), and market-making economics (q-020, q-029, q-044, q-045).
- [2026-07-06T16:30:56+00:00] pipeline (cycle 31): read budget 12 truncated 62 candidates -> 12 selected (dropped: 43 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 0 blocked, 1 already-seen, 2 invalid)
- [2026-07-06T16:35:54+00:00] pipeline (cycle 32): read budget 12 truncated 40 candidates -> 12 selected (dropped: 15 after-budget (unclassified), 0 domain-cap, 6 per-query-cap, 1 blocked, 5 already-seen, 1 invalid)
- [2026-07-06T16:36:09+00:00] pipeline (cycle 32): 0/12 useful reads for q-038 (12 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T16:36:09+00:00] worker BLOCKED on q-038 (HARD, count=2): no useful reads: 12 URLs selected, 12 read but none useful, 0 fetch-failed
- [2026-07-06T16:41:10+00:00] pipeline (cycle 33): read budget 12 truncated 40 candidates -> 12 selected (dropped: 10 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 2 blocked, 11 already-seen, 1 invalid)
- [2026-07-06T16:41:19+00:00] pipeline (cycle 33): 0/12 useful reads for q-038 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T16:41:19+00:00] worker BLOCKED on q-038 (HARD, count=4): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T16:44:51+00:00] evaluator (cycle 33) RETIRED q-038 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T16:45:14+00:00] pipeline (cycle 34): read budget 12 truncated 48 candidates -> 12 selected (dropped: 31 after-budget (unclassified), 0 domain-cap, 3 per-query-cap, 0 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T16:45:18+00:00] read dedup (cycle 34): https://www.federalregister.gov/documents/2026/06/03/2026-11020/policy-statement-concerning-the-listing-of-perpetual-contracts carries duplicate content of already-read https://www.ecfr.gov/current/title-17/chapter-I/part-38/subpart-C; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T16:50:43+00:00] pipeline (cycle 35): read budget 12 truncated 62 candidates -> 12 selected (dropped: 49 after-budget (unclassified), 0 domain-cap, 1 per-query-cap, 0 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T16:50:46+00:00] read dedup (cycle 35): https://www.federalregister.gov/documents/2026/03/16/2026-05105/prediction-markets carries duplicate content of already-read https://www.ecfr.gov/current/title-17/chapter-I/part-38/subpart-C; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T16:56:23+00:00] pipeline (cycle 36): read budget 12 truncated 40 candidates -> 12 selected (dropped: 27 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T16:56:32+00:00] pipeline (cycle 36): 0/12 useful reads for q-043 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T16:56:32+00:00] worker BLOCKED on q-043 (HARD, count=2): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T17:00:38+00:00] pipeline (cycle 37): read budget 12 truncated 40 candidates -> 12 selected (dropped: 25 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 1 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T17:04:31+00:00] evaluator (cycle 37) closed q-028 as immaterial: Redundant with q-055. Both ask to compute net post-fee profitability of documented edges against breakeven thresholds from q-042-c35. q-055 is more comprehensive (covers ALL edges: FLB, calibration, cross-platform arb, YES/NO asymmetry, not just FLB) and is specifically designed as a pure-synthesis task requiring no new source fetches. Closing q-028 avoids duplicate synthesis effort.
- [2026-07-06T17:04:31+00:00] evaluator (cycle 37) closed q-031 as immaterial: Redundant with q-054. Both ask whether ANY source documents a fully-costed net-profitable strategy. q-054 is more comprehensive (explicitly lists all friction components to check: platform fees, gas, spread, adverse selection, capital lockup, withdrawal/deposit friction, settlement risk) and builds on q-035-c30's finding that zero academic papers provide fee-adjusted analysis. Closing q-031 avoids duplicate effort.
- [2026-07-06T17:04:31+00:00] evaluator (cycle 37) closed q-047 as immaterial: Redundant with q-054. q-047 asks to 'identify every quantitative return claim stated as NET of all platform fees' across all 13 existing findings. q-054 asks 'does ANY source document a net-profitable strategy after all frictions' — q-047 is the data-gathering step for q-054's synthesis. Merging them into q-054 avoids splitting the synthesis into two questions that produce the same answer. If q-047's scan finds zero net-return claims (the likely outcome given q-035-c30), q-054's answer is trivially 'no' — a single question suffices.
- [2026-07-06T17:04:31+00:00] evaluator (cycle 37) closed q-057 as immaterial: Redundant with q-053. Both ask to verify the 'Kalshi overround 110-140%' claim. q-053 already specifies checking Le (2026), Galaxy Research report, Becker (2026), and NYT article for corroboration — the same four sources q-057 asks to check. The only difference is q-057 adds explicit source IDs; q-053 is broader. Closing q-057 as the narrower duplicate.
- [2026-07-06T17:04:31+00:00] evaluator (cycle 37) closed q-020 as immaterial: Substantially subsumed by q-044. q-020 asks for Polymarket maker rebate mechanics/formula/thresholds/independent verification/comparison to standard crypto models. q-044 asks more specifically for the CURRENT status of Polymarket's maker rewards program (whether paused, replaced, or modified) by reading the official docs.polymarket.com/trading/fees page — and also covers checking blog/GitHub/Twitter for updates. If the program is paused (as hinted by some sources), q-020's mechanical/formula questions become moot. q-044 is more current and targeted; closing q-020 avoids duplicate source fetches to the same documentation pages.
- [2026-07-06T17:05:05+00:00] pipeline (cycle 38): read budget 12 truncated 51 candidates -> 12 selected (dropped: 18 after-budget (unclassified), 0 domain-cap, 13 per-query-cap, 3 blocked, 4 already-seen, 1 invalid)
- [2026-07-06T17:05:15+00:00] pipeline (cycle 38): 0/12 useful reads for q-046 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:05:15+00:00] worker BLOCKED on q-046 (HARD, count=2): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T17:08:07+00:00] pipeline (cycle 39): read budget 12 truncated 54 candidates -> 12 selected (dropped: 24 after-budget (unclassified), 0 domain-cap, 14 per-query-cap, 2 blocked, 1 already-seen, 1 invalid)
- [2026-07-06T17:08:10+00:00] read dedup (cycle 39): https://defirate.com/learn/prediction-market-fees/ carries duplicate content of already-read https://defirate.com/prediction-markets/fees; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T17:08:21+00:00] pipeline (cycle 39): 0/12 useful reads for q-046 (11 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:08:21+00:00] worker BLOCKED on q-046 (HARD, count=4): no useful reads: 12 URLs selected, 11 read but none useful, 1 fetch-failed
- [2026-07-06T17:12:40+00:00] evaluator (cycle 39) RETIRED q-046 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T17:13:13+00:00] pipeline (cycle 40): read budget 12 truncated 40 candidates -> 12 selected (dropped: 23 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 3 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T17:13:26+00:00] pipeline (cycle 40): 0/12 useful reads for q-048 (4 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:13:26+00:00] worker BLOCKED on q-048 (HARD, count=2): no useful reads: 12 URLs selected, 4 read but none useful, 8 fetch-failed
- [2026-07-06T17:17:59+00:00] pipeline (cycle 41): read budget 12 truncated 46 candidates -> 12 selected (dropped: 26 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 3 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T17:18:08+00:00] pipeline (cycle 41): 0/12 useful reads for q-048 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:18:08+00:00] worker BLOCKED on q-048 (HARD, count=4): no useful reads: 12 URLs selected, 8 read but none useful, 4 fetch-failed
- [2026-07-06T17:22:21+00:00] evaluator (cycle 41) RETIRED q-048 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T17:22:21+00:00] evaluator (cycle 41) closed q-019 as immaterial: Redundant with five parallel resolution paths already open for the same target data. q-019 asks 'Does Kalshi distinguish API vs web-UI fees?' Five active questions (q-050 FIX Execution Report fees, q-051 Galaxy report fees, q-056 SDK source code fees, q-058 CFTC filings, q-059 Internet Archive) target the same underlying fact through different retrieval mechanisms. The answer to q-019 is automatically produced the moment any of these five succeeds. Keeping all six open duplicates effort on infrastructure-constrained source retrieval.
- [2026-07-06T17:22:21+00:00] evaluator (cycle 41) closed q-036 as immaterial: Immaterial — the absence of execution-quality data is already established as a key limitation. The Becker (2026) paper explicitly states it cannot observe bid-ask spreads from trade data (documented in q-035-c30). No other large-scale empirical study provides fill-rate or execution-quality metrics. The investigation has documented this gap (q-042-c35 uses estimated spread tiers from FalconX/Kaiko as a proxy, noting the assumption). Identifying which fraction of gross edge survives execution would require proprietary order-book data that no source in the evidence base possesses — further search cycles will not find what does not exist.
- [2026-07-06T17:22:21+00:00] evaluator (cycle 41) closed q-040 as immaterial: Immaterial — capacity quantification for a single anecdotal arbitrage trade does not change any conclusion about cross-platform arbitrage as a strategy class. The NYT article [src-you-can-make-free-money-on-polymarket-if, credibility 85] is already substantively cited in q-002-c04 and q-004-c05. Whether the Newsom 2028 arb could absorb $1K or $100K before the spread closed is a single-datapoint curiosity; it does not alter the investigation's conclusion that cross-platform arbs exist, persist for days-to-weeks, yield ~3% net in documented cases, and have unknown total capacity. The general capacity question is better addressed by the synthesis tasks q-054/q-055 and the consolidation question opened above.
- [2026-07-06T17:22:54+00:00] pipeline (cycle 42): read budget 12 truncated 44 candidates -> 12 selected (dropped: 19 after-budget (unclassified), 0 domain-cap, 9 per-query-cap, 2 blocked, 1 already-seen, 1 invalid)
- [2026-07-06T17:27:07+00:00] evaluator (cycle 42) closed q-060 as immaterial: IMMATERIAL: The Kalshi API authentication model contradiction has been adjudicated — RSA-PSS signed headers (KALSHI-ACCESS-KEY/SIGNATURE/TIMESTAMP) from docs.kalshi.com are authoritative for the current API. Whether Bearer tokens represent a deprecated v1 is a minor implementation footnote that does not change any conclusion about bot architecture, edge exploitability, or profitability. Bot builders should implement RSA-PSS.
- [2026-07-06T17:27:07+00:00] evaluator (cycle 42) closed q-041 as immaterial: IMMATERIAL: The YES/NO asymmetry math verification from the Becker (2026) paper would establish only whether the paper's own figures are internally consistent. It would not change any conclusion about strategy profitability, bot design, or regulatory constraints. The Becker paper is already flagged as 'not peer-reviewed, all findings provisional.' The YES/NO asymmetry is a point of curiosity for source-quality assessment, not a load-bearing claim for the investigation's conclusions.
- [2026-07-06T17:27:39+00:00] pipeline (cycle 43): read budget 12 truncated 35 candidates -> 12 selected (dropped: 15 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 0 blocked, 7 already-seen, 1 invalid)
- [2026-07-06T17:27:52+00:00] pipeline (cycle 43): 0/12 useful reads for q-050 (12 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:27:52+00:00] worker BLOCKED on q-050 (HARD, count=2): no useful reads: 12 URLs selected, 12 read but none useful, 0 fetch-failed
- [2026-07-06T17:31:25+00:00] evaluator (cycle 43) tried to close SEED question q-005 ("Substantially answered by existing findings. q-011-c09 documents Kalshi's CFTC-regulated DCM status (US-only, KYC-gated) and Polymarket Global's US-person prohibition. q-018-c21 documents that: (a) Polymarket Global clob.polymarket.com remains geoblocked for US persons, (b) Polymarket US exists but has no documented API for bot operators, (c) international traders cannot access Kalshi (requires US presence/SSN). These structural constraints make simultaneous Kalshi+Polymarket operation impossible for both US persons (Polymarket Global banned) and international traders (Kalshi inaccessible). Additional geographic/KYC detail would enrich context but would not change this binary conclusion.") — REFUSED: initializer questions are the mandated scope (blocked 0x; exhausted-scope close needs 2)
- [2026-07-06T17:31:25+00:00] evaluator (cycle 43) tried to close SEED question q-010 ('Redundant with q-054 (synthesis: does ANY source document a net-profitable strategy?) and q-055 (synthesis: map each edge against breakeven thresholds). These synthesis questions will produce the honest quantification and survivorship-bias assessment that q-010 requests. Keeping q-010 open duplicates synthesis effort. The survivorship-bias concern is already flagged in q-009-c08 and q-035-c30.') — REFUSED: initializer questions are the mandated scope (blocked 0x; exhausted-scope close needs 2)
- [2026-07-06T17:31:25+00:00] evaluator (cycle 43) closed q-062 as immaterial: Immaterial. Kalshi's demo/sandbox environment (external-api.demo.kalshi.co) uses simulated fills and may not reflect production fee rates. Even if the demo shows 0% fees, this does not resolve the production fee question — demo environments commonly waive fees for testing. Conversely, if the demo applies the standard formula, that does not prove production API orders use the same rate (there could be a production-only API fee waiver). The demo fee behavior is non-probative for the central fee contradiction.
- [2026-07-06T17:31:25+00:00] evaluator (cycle 43) closed q-063 as immaterial: Redundant with q-052. q-052 asks for 'Kalshi's Terms of Service at kalshi.com/terms and Polymarket's Terms of Service at polymarket.com/terms — the legal ToS pages, not the API documentation — for their specific provisions on automated trading, algorithmic trading, bots, and programmatic order submission.' q-063 isolates the Polymarket side only. Since q-052 covers both platforms' legal ToS pages (the exact source q-063 targets), keeping q-063 open fragments the same retrieval into two questions. Close q-063 as the narrower duplicate; keep q-052 as the comprehensive request.
- [2026-07-06T17:41:10+00:00] evaluator (cycle 44) closed q-054 as immaterial: Redundant with q-061. q-054 asks to synthesize ALL findings into a yes/no answer on whether ANY source documents a net-profitable strategy. q-061 asks to synthesize ALL findings into a reader-complete answer to the original six-facet research question — which necessarily includes the net-profitability answer as part of Facet 5. q-061 is the more comprehensive consolidation. Running both would produce the same synthesis work twice.
- [2026-07-06T17:41:10+00:00] evaluator (cycle 44) closed q-055 as immaterial: Redundant with q-061. q-055 asks to map each documented gross edge against breakeven thresholds from q-042-c35 and produce a table showing which edges clear which thresholds. This is a sub-component of q-061's six-facet consolidation, which must necessarily include edge-vs-breakeven comparison as part of Facet 5. Running both would duplicate synthesis effort.
- [2026-07-06T17:41:10+00:00] evaluator (cycle 44) closed q-066 as immaterial: Redundant with q-061. q-066 asks for a definitive answer to Facet 5 specifically (profitability outlook under both fee scenarios, edge-vs-breakeven mapping, maximum plausible return, missing cost categories). q-061's comprehensive six-facet consolidation necessarily includes Facet 5 at this level of detail. q-066 is a narrower subset of q-061's scope.
- [2026-07-06T17:41:10+00:00] evaluator (cycle 44) closed q-045 as immaterial: Answered by existing finding q-035-c30. q-045 asks whether the Becker (2026) +1.12% maker gross excess return is fee-adjusted or gross-only, and whether the paper accounts for maker-fee reimbursement, spread crossing, adverse selection, and capital lockup. q-035-c30 definitively answers: (a) the paper computes returns gross of platform fees using formula r_i = (100·o_i − p_i)/p_i with no fee deduction, (b) the paper explicitly states 'we cannot directly observe the bid-ask spread' from historical trade data, and (c) no paper provides fee-adjusted or fully-loaded net returns. The +1.12% is confirmed as a GROSS return only. Further retrieval of the Becker paper would not change this conclusion.
- [2026-07-06T17:41:10+00:00] evaluator (cycle 44) closed q-064 as immaterial: Immaterial to the investigation's practical conclusions. q-064 asks to verify the mathematical consistency of Becker (2026)'s -41% YES / +23% NO excess return figures at 1¢. Whether these specific figures are mis-transcribed or the paper's own numbers are internally contradictory, it does not change any conclusion about bot architecture (Facet 4), regulatory constraints (Facet 6), platform API design (Facet 4), or the practical feasibility of automated trading. The Becker paper is ALREADY flagged in q-013-c13 as 'not peer-reviewed, all findings provisional' and in q-035-c30 as providing only gross returns. Its quantitative claims are already treated with appropriate caution. Verifying this single data point's internal consistency would enrich source-quality assessment but would not alter any actionable conclusion for a bot operator. The investigation has more load-bearing gaps (seed questions q-003/q-005/q-006/q-010, Kalshi fee resolution, Facet 3 deliverable) that should consume the remaining budget.
- [2026-07-06T17:41:43+00:00] pipeline (cycle 45): read budget 12 truncated 46 candidates -> 12 selected (dropped: 28 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 2 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T17:48:01+00:00] pipeline (cycle 46): 0/8 useful reads for q-052 (6 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:48:02+00:00] worker BLOCKED on q-052 (HARD, count=2): no useful reads: 8 URLs selected, 6 read but none useful, 2 fetch-failed
- [2026-07-06T17:51:45+00:00] pipeline (cycle 47): read budget 12 truncated 38 candidates -> 12 selected (dropped: 21 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 1 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T17:53:24+00:00] pipeline (cycle 47): 0/12 useful reads for q-052 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:53:24+00:00] worker BLOCKED on q-052 (HARD, count=4): no useful reads: 12 URLs selected, 8 read but none useful, 4 fetch-failed
- [2026-07-06T17:55:47+00:00] evaluator (cycle 47) RETIRED q-052 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T17:55:47+00:00] evaluator (cycle 47) closed q-067 as immaterial: Redundant with q-068. Both questions target resolving the Bürgi/Becker paper-identity contradiction. q-067 asks to re-examine Becker (2026)'s bibliography for a Bürgi citation; q-068 asks to read the Substack article 'What Five New Academic Papers Say About Prediction Markets' which covers both papers and can distinguish them. q-068 is the more promising retrieval path (Substack web article is more likely accessible than academic PDF bibliography) and its answer subsumes q-067's narrower request. Close q-067 to avoid fragmenting the same investigation across two questions.
- [2026-07-06T17:56:19+00:00] pipeline (cycle 48): read budget 12 truncated 37 candidates -> 12 selected (dropped: 23 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 0 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T17:56:40+00:00] pipeline (cycle 48): 0/12 useful reads for q-053 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T17:56:40+00:00] worker BLOCKED on q-053 (HARD, count=2): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T18:01:26+00:00] evaluator (cycle 48) closed q-070 as immaterial: Redundant with q-071. q-070 asks to read the Le (2026) paper specifically for Kalshi spread/overround data. q-071 asks to synthesize spread, liquidity, market-depth, and news-reaction data from ALL already-read sources including the Le (2026) paper, the MetaMask/FalconX/Kaiko article, the Becker (2026) paper, the Galaxy Research report, and the NYT article. q-071's broader synthesis subsumes q-070's narrower task and does not require a new source fetch. Running both fragments the same synthesis effort across two questions.
- [2026-07-06T18:01:42+00:00] pipeline (cycle 49): read budget 12 truncated 40 candidates -> 12 selected (dropped: 23 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T18:01:50+00:00] pipeline (cycle 49): 0/12 useful reads for q-053 (7 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:01:50+00:00] worker BLOCKED on q-053 (HARD, count=4): no useful reads: 12 URLs selected, 7 read but none useful, 5 fetch-failed
- [2026-07-06T18:06:32+00:00] evaluator (cycle 49) RETIRED q-053 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T18:07:12+00:00] pipeline (cycle 50): 0/8 useful reads for q-056 (7 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:07:12+00:00] worker BLOCKED on q-056 (HARD, count=2): no useful reads: 8 URLs selected, 7 read but none useful, 1 fetch-failed
- [2026-07-06T18:10:51+00:00] evaluator (cycle 50) closed q-077 as immaterial: NEAR-DUPLICATE of q-068. Both ask to read the same Substack article 'What Five New Academic Papers Say About Prediction Markets' at nexteventhorizon.substack.com to resolve the Bürgi/Becker paper identity. q-068 is the earlier, more specific version (requests exact language distinguishing the papers, exact fee-adjusted figures, DOIs/institutional affiliations). q-077 adds no scope beyond q-068. Closing the duplicate avoids fragmenting the same retrieval across two questions.
- [2026-07-06T18:10:51+00:00] evaluator (cycle 50) closed q-029 as immaterial: SUBSUMED by q-069. q-029 asks for Kalshi-specific maker rebate and adverse selection data from Becker (2026). q-069 asks for a comprehensive synthesis of ALL market-making economics across both platforms (maker fees, rebates, adverse selection, breakeven thresholds, practitioner results) — which necessarily covers Kalshi-specific findings. q-029 is a sub-component; keeping it open fragments the synthesis effort. The Becker (2026) maker +1.12% gross edge and its category decomposition are already documented in q-013-c13 and q-035-c30.
- [2026-07-06T18:11:31+00:00] pipeline (cycle 51): 0/8 useful reads for q-056 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:11:31+00:00] worker BLOCKED on q-056 (HARD, count=4): no useful reads: 8 URLs selected, 8 read but none useful, 0 fetch-failed
- [2026-07-06T18:15:13+00:00] evaluator (cycle 51) RETIRED q-056 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T18:15:46+00:00] pipeline (cycle 52): read budget 12 truncated 46 candidates -> 12 selected (dropped: 31 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 1 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T18:15:49+00:00] read dedup (cycle 52): https://www.ecfr.gov/current/title-17/chapter-I/part-40/section-40.6 carries duplicate content of already-read https://www.ecfr.gov/current/title-17/chapter-I/part-38/subpart-C; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T18:15:49+00:00] read dedup (cycle 52): https://www.federalregister.gov/documents/2024/06/10/2024-12125/event-contracts carries duplicate content of already-read https://www.ecfr.gov/current/title-17/chapter-I/part-38/subpart-C; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T18:15:56+00:00] pipeline (cycle 52): 0/12 useful reads for q-058 (11 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:15:57+00:00] worker BLOCKED on q-058 (HARD, count=2): no useful reads: 12 URLs selected, 11 read but none useful, 1 fetch-failed
- [2026-07-06T18:21:33+00:00] pipeline (cycle 53): read budget 12 truncated 57 candidates -> 12 selected (dropped: 42 after-budget (unclassified), 0 domain-cap, 3 per-query-cap, 0 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T18:21:36+00:00] read dedup (cycle 53): https://www.federalregister.gov/documents/2026/06/16/2026-12034/self-regulatory-organizations-cboe-exchange-inc-notice-of-filing-and-immediate-effectiveness-of-a carries duplicate content of already-read https://www.ecfr.gov/current/title-17/chapter-I/part-38/subpart-C; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T18:22:12+00:00] pipeline (cycle 53): 0/12 useful reads for q-058 (11 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:22:12+00:00] worker BLOCKED on q-058 (HARD, count=4): no useful reads: 12 URLs selected, 11 read but none useful, 1 fetch-failed
- [2026-07-06T18:26:47+00:00] evaluator (cycle 53) RETIRED q-058 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T18:27:29+00:00] pipeline (cycle 54): 0/7 useful reads for q-059 (5 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:27:30+00:00] worker BLOCKED on q-059 (HARD, count=2): no useful reads: 7 URLs selected, 5 read but none useful, 2 fetch-failed
- [2026-07-06T18:30:39+00:00] pipeline (cycle 55): read budget 12 truncated 36 candidates -> 12 selected (dropped: 18 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 1 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T18:34:35+00:00] evaluator (cycle 55) closed q-079 as immaterial: The Bürgi/Becker contradiction has been adjudicated in this evaluation cycle (see contradiction #1). The adjudication finds separate papers based on irreconcilable differences in sample size (300K vs 72.1M), authorship, institutional affiliation, and fee treatment. A separate synthesis question to resolve the same contradiction from existing findings would duplicate this analysis. q-068 (reading the Substack article directly) and q-035-c30 amendment are the appropriate next steps.
- [2026-07-06T18:34:52+00:00] pipeline (cycle 56): read budget 12 truncated 39 candidates -> 12 selected (dropped: 22 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 1 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T18:40:10+00:00] evaluator (cycle 56) closed q-075 as immaterial: IMMATERIAL. Polymarket's fee rates are already documented from official sources at credibility 90 (docs.polymarket.com/trading/fees via [src-trading-fees-on-polymarket]). On-chain verification via Polygon block explorer would add decimal-point precision but would not change any conclusion about strategy profitability, breakeven thresholds, or bot architecture. The four seed questions that remain OPEN (q-003, q-005, q-006, q-010) plus the Kalshi fee contradiction are the binding constraints on conclusiveness — verifying Polymarket fees on-chain consumes budget without advancing any of these gaps.
- [2026-07-06T18:40:42+00:00] pipeline (cycle 57): read budget 12 truncated 31 candidates -> 12 selected (dropped: 14 after-budget (unclassified), 0 domain-cap, 5 per-query-cap, 0 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T18:40:46+00:00] read dedup (cycle 57): https://www.federalregister.gov/documents/2026/06/12/2026-11854/prediction-markets-public-interest-determinations carries duplicate content of already-read https://www.ecfr.gov/current/title-17/chapter-I/part-38/subpart-C; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T18:40:54+00:00] pipeline (cycle 57): 0/12 useful reads for q-065 (11 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:40:54+00:00] worker BLOCKED on q-065 (HARD, count=2): no useful reads: 12 URLs selected, 11 read but none useful, 1 fetch-failed
- [2026-07-06T18:45:26+00:00] evaluator (cycle 57) closed q-082 as immaterial: Redundant with q-068. Both target resolution of the Bürgi/Becker paper-identity contradiction. q-068 reads the Substack article 'What Five New Academic Papers Say About Prediction Markets' at nexteventhorizon.substack.com — this article explicitly covers both papers and can distinguish them. q-082 asks to re-read the Becker (2026) paper's bibliography for a Bürgi citation. q-068 is the more direct and likely more informative resolution path (the Substack article compares papers side-by-side; a bibliography citation is a weaker signal). If q-068 succeeds and confirms the papers are distinct, q-082's narrower bibliography check is unnecessary. If q-068 fails (Substack inaccessible), q-082 still won't help because re-reading an already-read paper provided no fee data in the original read (q-035-c30). Close to avoid fragmenting the single paper-identity investigation across two questions.
- [2026-07-06T18:45:43+00:00] pipeline (cycle 58): read budget 12 truncated 39 candidates -> 12 selected (dropped: 20 after-budget (unclassified), 0 domain-cap, 6 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T18:45:53+00:00] pipeline (cycle 58): 0/12 useful reads for q-065 (11 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:45:53+00:00] worker BLOCKED on q-065 (HARD, count=4): no useful reads: 12 URLs selected, 11 read but none useful, 1 fetch-failed
- [2026-07-06T18:51:44+00:00] evaluator (cycle 58) RETIRED q-065 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T18:51:44+00:00] evaluator (cycle 58) closed q-076 as immaterial: DIMINISHING RETURNS after fee adjudication. q-076 asks to read Kalshi's event-contract FIX Execution Report docs for fee data. The margin FIX docs (q-050-c44) already confirmed Kalshi uses MiscFeeAmt (tag 137) to return actual fee dollar amounts on trade fills — confirming fees ARE charged on API trades and contradicting the 0% API fee claim. The Kalshi fee model has been adjudicated in this evaluation cycle (standard formula by preponderance of evidence). Whether event-contract FIX reports use identical MiscFeeAmt tags to margin FIX reports would add precision but would not change the adjudication. The docs.kalshi.com/fix URL may also be subject to the same HTTP 403 blocks that retired 5+ other Kalshi documentation resolution paths.
- [2026-07-06T18:51:53+00:00] pipeline (cycle 59): read budget 12 truncated 40 candidates -> 12 selected (dropped: 20 after-budget (unclassified), 0 domain-cap, 3 per-query-cap, 2 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T18:52:02+00:00] pipeline (cycle 59): 0/12 useful reads for q-068 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:52:02+00:00] worker BLOCKED on q-068 (HARD, count=2): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T18:56:32+00:00] evaluator (cycle 59) closed q-078 as immaterial: DIMINISHING RETURNS after Kalshi fee adjudication. The Kalshi fee rate has been formally adjudicated to the standard formula (maker 0.0175/taker 0.07) by preponderance of evidence. q-078 asks to search Kalshi's GitHub organization for fee-related code — even if successful, this would add decimal-point confirmation to an already-settled conclusion. Five prior resolution paths targeting Kalshi corporate infrastructure (docs.kalshi.com fee page, help center, CFTC filings, SEC EDGAR, API blog post) were all HARD BLOCKED. GitHub may be independently accessible but the finding would not change any conclusion, and cycles are better spent on the unresolved Bürgi/Becker verification (q-068, q-085) and completing the four open seed questions via their synthesis children (q-069, q-071, q-072, q-073).
- [2026-07-06T18:56:32+00:00] evaluator (cycle 59) closed q-080 as immaterial: DIMINISHING RETURNS after Kalshi fee adjudication. q-080 asks to search Reddit, Discord, and developer forums for practitioner screenshots of Kalshi trade confirmations showing actual fee amounts. The fee rate has been adjudicated to the standard formula. Practitioner screenshots would add anecdotal confirmation but would not be authoritative (they could show a specific account's fee tier, not the platform-wide rate). Three independent resolution paths already confirm fees ARE charged: FIX Execution Reports populate MiscFeeAmt (q-050-c44), Galaxy Research notes Kalshi 'charge[s] significantly higher fees' (q-051-c45), and multiple secondary sources converge on the same formula coefficients (q-002-c04, q-004-c05, q-043-c37). Reddit/forum searches are infrastructure-independent but the expected evidentiary value is low (unsourced screenshots, selection bias toward users who notice fees) relative to the formal adjudication already in place.
- [2026-07-06T18:56:58+00:00] pipeline (cycle 60): read budget 12 truncated 32 candidates -> 12 selected (dropped: 13 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 2 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T18:57:07+00:00] pipeline (cycle 60): 0/12 useful reads for q-068 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T18:57:07+00:00] worker BLOCKED on q-068 (HARD, count=4): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T18:59:54+00:00] evaluator (cycle 60) RETIRED q-068 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T18:59:54+00:00] evaluator (cycle 60) closed q-073 as immaterial: SUPERSEDED by newly opened synthesis question (q-010-child) that incorporates the three adjudications made in this evaluation cycle: (a) Kalshi fee rate settled to standard formula (not bifurcated 0%-vs-standard scenarios), (b) Bürgi/Becker confirmed as separate papers with different fee treatment, (c) Kalshi overround 110-140% claim rejected as uncorroborated. q-073 was designed as a bifurcated-scenario synthesis under fee uncertainty; the adjudications make that hedge unnecessary. The replacement question produces a more definitive answer with settled premises.
- [2026-07-06T18:59:54+00:00] evaluator (cycle 60) closed q-086 as immaterial: SUPERSEDED by newly opened synthesis question (q-010-child) that incorporates the three evaluator adjudications. q-086 was opened as a synthesis superseding q-073 but was itself designed before the evaluator's formal adjudication of the Kalshi fee rate, Bürgi/Becker identity, and overround claim. The new synthesis question uses settled adjudicated premises rather than tentative assumptions.
- [2026-07-06T18:59:54+00:00] evaluator (cycle 60) closed q-084 as immaterial: SUPERSEDED. The Bürgi/Becker paper-identity contradiction has been FORMALLY ADJUDICATED in this evaluation cycle (separate papers). q-084 was opened to amend q-035-c30 based on a synthesis of existing findings. The adjudication renders q-084 unnecessary — the conclusion that q-035-c30 requires amendment is now an evaluator ruling, not a worker finding. The amendment will be incorporated into the Facet 5 synthesis (new q-010-child) which explicitly states the corrected evidence-base assessment.
- [2026-07-06T18:59:54+00:00] evaluator (cycle 60) closed q-087 as immaterial: SUPERSEDED. q-087 was opened to produce a corrected evidence-base assessment using adjudicated determinations. The three key determinations (Bürgi≠Becker, standard fee formula, overround rejected) are now formal evaluator adjudications in this cycle. The corrected assessment will be incorporated into the Facet 5 synthesis (new q-010-child) rather than being a standalone finding.
- [2026-07-06T19:00:03+00:00] pipeline (cycle 61): read budget 12 truncated 64 candidates -> 12 selected (dropped: 46 after-budget (unclassified), 0 domain-cap, 3 per-query-cap, 2 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T19:03:18+00:00] evaluator (cycle 61) closed q-083 as immaterial: MOOT after formal fee adjudication. q-083 asked to synthesize the BEST estimate for Kalshi's actual fee rate. The evaluator has now FORMALLY adjudicated the fee contradiction: standard formula (maker 0.0175/taker 0.07) by preponderance of evidence. A worker finding would merely restate the evaluator's ruling without adding new evidence. All downstream profitability calculations should use the adjudicated rate.
- [2026-07-06T19:03:18+00:00] evaluator (cycle 61) closed q-074 as immaterial: NEAR-DUPLICATE of q-089. Both target Internet Archive Wayback Machine retrieval of kalshi.com/terms and polymarket.com/terms. q-089 is more specific (specifies snapshot dates mid-2025 to mid-2026, includes archive.is and Google Cache as fallback sources). Keeping both open fragments the same retrieval task across two questions.
- [2026-07-06T19:03:45+00:00] pipeline (cycle 62): read budget 12 truncated 71 candidates -> 12 selected (dropped: 42 after-budget (unclassified), 0 domain-cap, 8 per-query-cap, 1 blocked, 7 already-seen, 1 invalid)
- [2026-07-06T19:07:55+00:00] evaluator (cycle 62) closed q-071 as immaterial: SUPERSEDED by the new combined seed-resolution synthesis question, which includes the spread/liquidity/news-reaction synthesis for q-003 as one of its four components. Avoiding fragmentation of synthesis work across separate questions.
- [2026-07-06T19:07:55+00:00] evaluator (cycle 62) closed q-072 as immaterial: SUPERSEDED by the new combined seed-resolution synthesis question, which includes the geographic/KYC synthesis for q-005 as one of its four components. Avoiding fragmentation of synthesis work across separate questions.
- [2026-07-06T19:07:55+00:00] evaluator (cycle 62) closed q-090 as immaterial: SUPERSEDED by the new combined seed-resolution synthesis question, which includes the profitability assessment for q-010 using adjudicated premises as one of its four components. A single worker task produces all four seed resolutions more efficiently than three separate synthesis questions.
- [2026-07-06T19:08:32+00:00] pipeline (cycle 63): 0/10 useful reads for q-088 (4 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:08:32+00:00] worker BLOCKED on q-088 (HARD, count=2): no useful reads: 10 URLs selected, 4 read but none useful, 6 fetch-failed
- [2026-07-06T19:11:29+00:00] pipeline (cycle 64): read budget 12 truncated 43 candidates -> 12 selected (dropped: 19 after-budget (unclassified), 0 domain-cap, 5 per-query-cap, 0 blocked, 5 already-seen, 2 invalid)
- [2026-07-06T19:11:40+00:00] pipeline (cycle 64): 0/12 useful reads for q-088 (4 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:11:40+00:00] worker BLOCKED on q-088 (HARD, count=4): no useful reads: 12 URLs selected, 4 read but none useful, 8 fetch-failed
- [2026-07-06T19:14:10+00:00] evaluator (cycle 64) RETIRED q-088 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T19:14:44+00:00] pipeline (cycle 65): 0/11 useful reads for q-089 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:14:44+00:00] worker BLOCKED on q-089 (HARD, count=2): no useful reads: 11 URLs selected, 9 read but none useful, 2 fetch-failed
- [2026-07-06T19:19:53+00:00] evaluator (cycle 65) closed q-089 as immaterial: EXHAUSTED SCOPE. Two independent retrieval paths for Kalshi and Polymarket Terms of Service pages have now failed after multiple hard blocks: (a) q-052 attempted direct retrieval of kalshi.com/terms and polymarket.com/terms — retired exhausted after 4 hard blocks (cycles 46-47), (b) q-089 attempted Internet Archive Wayback Machine retrieval of the same pages — 2 hard blocks in cycles 64-65, with no useful reads. Three additional archive paths (archive.is, Google Cache) were specified as fallbacks but all depend on the same backend indexing infrastructure that may be rate-limiting or blocking the run's reader. The ToS gap is now a documented limitation: primary ToS pages are inaccessible to the investigation's retrieval infrastructure. The gap is acknowledged in unmet_criteria with the best-available secondary evidence (polymarket-agents ToS prohibition on US persons from q-018-c21; Kalshi API documentation implying permission via FIX/REST API availability). Further retrieval cycles are unlikely to succeed and would consume remaining budget ($0.98) without probable return.
- [2026-07-06T19:19:53+00:00] evaluator (cycle 65) closed q-092 as immaterial: MOOT AFTER FORMAL ADJUDICATION. The evaluator has formally adjudicated the Kalshi overround 110-140% contradiction in this evaluation cycle: the claim is ruled UNCORROBORATED, sourced only to a credibility-60 affiliate site, and inconsistent with every higher-credibility source. The adjudication is part of this evaluation's formal record and carries the same authoritative weight as a factual determination. The amendment task (flagging q-004-c05's overround claim as uncorroborated) is now a straightforward application of the evaluator's ruling and will be executed by the consolidated amendment synthesis (the first new_question in this cycle, which covers all three corrections). Keeping q-092 open as a separate task would fragment the same correction across two questions.
- [2026-07-06T19:19:53+00:00] evaluator (cycle 65) closed q-093 as immaterial: MOOT AFTER FORMAL ADJUDICATION. The evaluator has formally adjudicated the Kalshi API fee contradiction in this evaluation cycle: the '0% API fees' claim is REJECTED; the standard formula (maker 0.0175/taker 0.07 × C × P × (1-P) with monthly reimbursement above $10) is the best-estimate rate by preponderance of evidence. The adjudication is part of this evaluation's formal record. The amendment task (replacing q-007-c06's 0% claim with the standard formula) will be executed by the consolidated amendment synthesis (the first new_question in this cycle). Keeping q-093 open as a separate task fragments the same correction.
- [2026-07-06T19:20:28+00:00] pipeline (cycle 66): 0/11 useful reads for q-091 (5 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:20:28+00:00] worker BLOCKED on q-091 (HARD, count=2): no useful reads: 11 URLs selected, 5 read but none useful, 6 fetch-failed
- [2026-07-06T19:23:30+00:00] evaluator (cycle 66) closed q-091 as immaterial: SUPERSEDED by consolidation amendment q-095. q-091 asks to amend q-035-c30 to correct the Bürgi/Becker error — this is one of the three corrections consolidated into q-095 (alongside the fee-rate correction for q-007-c06 and the overround-flag for q-004-c05). q-091 was also HARD BLOCKED in cycle 66 despite being a pure-synthesis task. Closing q-091 avoids fragmenting the same amendment work across two questions.
- [2026-07-06T19:23:54+00:00] pipeline (cycle 67): read budget 12 truncated 48 candidates -> 12 selected (dropped: 20 after-budget (unclassified), 0 domain-cap, 12 per-query-cap, 0 blocked, 4 already-seen, 0 invalid)
- [2026-07-06T19:29:03+00:00] evaluator (cycle 67) closed q-044 as immaterial: SUPERSEDED. q-094-c67 already confirms the Polymarket Liquidity Incentive Program is active as of July 2026 with extensive documentation: quadratic scoring formula S(v,s)=((v-s)/v)²×b, daily reward pools (Politics $250/day, Sports $500-$2500/day, Climate $1000/day, etc.), World Cup 2026 escalating caps ($6,110→$52,000 per game), minimum $1/day payout threshold, two-sided quoting requirement (single-sided earns 1/3 score at 0.10-0.90, zero outside), and midnight UTC on-chain settlement. q-069-c61 independently confirms LIP is active with an updated schedule effective July 2, 2026. No further independent verification via docs.polymarket.com/trading/fees is needed — the program's active status and mechanics are confirmed by two separate findings. Close q-044 to avoid redundant source fetches to the same documentation pages.
- [2026-07-06T19:29:28+00:00] pipeline (cycle 68): read budget 12 truncated 33 candidates -> 12 selected (dropped: 15 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 1 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T19:29:30+00:00] read dedup (cycle 68): https://arxiv.org/html/2606.07811v1 carries duplicate content of already-read https://arxiv.org/html/2606.07811; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T19:34:16+00:00] pipeline (cycle 69): read budget 12 truncated 49 candidates -> 12 selected (dropped: 30 after-budget (unclassified), 0 domain-cap, 6 per-query-cap, 1 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T19:34:25+00:00] pipeline (cycle 69): 0/12 useful reads for q-096 (7 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:34:25+00:00] worker BLOCKED on q-096 (HARD, count=2): no useful reads: 12 URLs selected, 7 read but none useful, 5 fetch-failed
- [2026-07-06T19:37:28+00:00] evaluator (cycle 69) closed q-081 as immaterial: IMMATERIAL given remaining budget ($0.88) and existing evidence. q-081 targets spread data from the Le (2026) paper and MetaMask/FalconX/Kaiko article. The FalconX/Kaiko spread tiers are already documented in q-042-c35 (1-3¢ thick, 3-7¢ mid, 8-15¢ niche). The spread narrowing trend is documented in q-094-c67 (4.5%→1.2%, 2023-2025). The Le (2026) paper PDF at arxiv.org is likely to hard-block (as multiple academic PDF retrievals have in this run). Even if successfully retrieved, additional spread precision would not change any conclusion about strategy profitability — no documented strategy has been verified as net-profitable regardless of spread granularity. The remaining budget is better allocated to the Bürgi primary-paper retrieval (q-098) and the seed-question synthesis tasks (q-096, q-097).
- [2026-07-06T19:37:36+00:00] pipeline (cycle 70): read budget 12 truncated 49 candidates -> 12 selected (dropped: 31 after-budget (unclassified), 0 domain-cap, 3 per-query-cap, 1 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T19:37:44+00:00] pipeline (cycle 70): 0/12 useful reads for q-096 (7 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:37:45+00:00] worker BLOCKED on q-096 (HARD, count=4): no useful reads: 12 URLs selected, 7 read but none useful, 5 fetch-failed
- [2026-07-06T19:39:50+00:00] evaluator (cycle 70) RETIRED q-096 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T19:39:50+00:00] evaluator (cycle 70) proposed a near-duplicate of q-096; dropped 'SYNTHESIS (no new source fetches — ZERO FETCHES ALLOWED): Re'
- [2026-07-06T19:40:17+00:00] pipeline (cycle 71): read budget 12 truncated 63 candidates -> 12 selected (dropped: 50 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T19:40:25+00:00] pipeline (cycle 71): 0/12 useful reads for q-098 (11 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:40:25+00:00] worker BLOCKED on q-098 (HARD, count=2): no useful reads: 12 URLs selected, 11 read but none useful, 1 fetch-failed
- [2026-07-06T19:44:15+00:00] evaluator (cycle 71) closed q-099 as immaterial: Redundant with q-097. q-099 asks to synthesize spread/liquidity data for q-003 only. q-097 asks to synthesize answers for q-003, q-005, and q-006 simultaneously using ONLY existing findings. Any spread/liquidity/FLB data relevant to q-003 that q-097 would use is a superset of what q-099 requests. Keeping both open fragments the same synthesis effort across two worker tasks, risking inconsistent answers and wasting budget. q-097 remains open as the comprehensive synthesis.
- [2026-07-06T19:44:51+00:00] pipeline (cycle 72): 0/9 useful reads for q-098 (6 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:44:51+00:00] worker BLOCKED on q-098 (HARD, count=4): no useful reads: 9 URLs selected, 6 read but none useful, 3 fetch-failed
- [2026-07-06T19:47:50+00:00] evaluator (cycle 72) RETIRED q-098 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T19:47:57+00:00] pipeline (cycle 73): read budget 12 truncated 87 candidates -> 12 selected (dropped: 71 after-budget (unclassified), 0 domain-cap, 1 per-query-cap, 0 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T19:49:10+00:00] pipeline (cycle 73): 0/12 useful reads for q-100 (7 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:49:11+00:00] worker BLOCKED on q-100 (HARD, count=2): no useful reads: 12 URLs selected, 7 read but none useful, 5 fetch-failed
- [2026-07-06T19:53:14+00:00] pipeline (cycle 74): read budget 12 truncated 55 candidates -> 12 selected (dropped: 36 after-budget (unclassified), 0 domain-cap, 5 per-query-cap, 0 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T19:53:29+00:00] worker BLOCKED on q-100 (soft, count=3): The assigned question (q-100) requires synthesis across approximately 30+ specific finding IDs (q-001-c03 through q-095-c68) and three formal adjudications to compute quantified edge-versus-cost comparisons, maximum plausible returns, and a corrected central negative finding. However, the only reader summaries provided are [src-polymarketguide-trading-rewards] and [src-kalshi-fees-explained-for-2026-understan]. These two sources supply partial fee-structure information and reward-program details but contain none of the required data on gross edges (FLB, calibration, cross-platform arb, YES/NO asymmetry), breakeven thresholds from q-042-c35, Polymarket maker fee and LIP reward specifics per q-069-c61/q-094-c67, the structural impossibility of simultaneous dual-platform access per q-018-c21, Becker vs. Bürgi return figures, or the extensive list of unquantified frictions. Without access to the full set of cited findings, a faithful synthesis is impossible — no claim in the finding would have a supporting citation from the menu. Per the instructions, the worker MUST NOT fabricate or go beyond what the summaries support.
- [2026-07-06T19:56:43+00:00] read dedup (cycle 75): https://docs.kalshi.com/ carries duplicate content of already-read https://docs.kalshi.com/welcome; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T19:56:50+00:00] pipeline (cycle 75): 0/4 useful reads for q-100 (3 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T19:56:50+00:00] worker BLOCKED on q-100 (HARD, count=5): no useful reads: 4 URLs selected, 3 read but none useful, 1 fetch-failed
- [2026-07-06T20:00:35+00:00] evaluator (cycle 75) RETIRED q-100 as exhausted scope after 5 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T20:00:35+00:00] evaluator (cycle 75) closed q-097 as immaterial: HARD BLOCKED. Worker attempted to fetch new URLs despite explicit NO-FETCH directive in the question text. Superseded by q-101, q-102, q-103 which have stronger LOCAL-FILE-ONLY instructions with explicit file paths.
- [2026-07-06T20:00:44+00:00] pipeline (cycle 76): read budget 12 truncated 61 candidates -> 12 selected (dropped: 34 after-budget (unclassified), 0 domain-cap, 8 per-query-cap, 4 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T20:01:01+00:00] worker BLOCKED on q-101 (soft, count=1): I am instructed to use ONLY the Read tool to read local finding files (e.g., findings/q-042-c35.md, findings/q-001-c03.md, etc.) and to fetch ZERO URLs. The provided context contains only a single reader summary for [src-best-prediction-market-platforms-in-2026], which is a promotional blog — not a local finding file. I have no access to any of the required local finding files (q-042-c35, q-001-c03, q-012-c11, q-013-c13, q-002-c04, q-004-c05, q-018-c21, q-069-c61, q-085-c62) that the question specifies must be read. Without those files, I cannot extract breakeven thresholds, gross edge estimates, compare edges to costs, estimate realistic returns, or provide the other required steps. The sole available source is insufficient and of the wrong type to answer this synthesis question.
- [2026-07-06T20:03:39+00:00] evaluator (cycle 76) closed q-104 as immaterial: NEAR-DUPLICATE of q-101. Both target seed question q-010 (Facet 5: honest expected returns) with identical 'read local files only, zero URL fetches' directives. q-101 is the earlier version with a clearer step-by-step structure. Keeping both fragments synthesis effort across two worker tasks.
- [2026-07-06T20:03:39+00:00] evaluator (cycle 76) closed q-105 as immaterial: NEAR-DUPLICATE of q-102. Both target seed question q-003 (thin liquidity/spreads/news-reaction) with identical 'read local files only, zero URL fetches' directives. q-102 has more comprehensive file-read instructions. Keeping both fragments synthesis effort.
- [2026-07-06T20:03:39+00:00] evaluator (cycle 76) closed q-106 as immaterial: NEAR-DUPLICATE of q-103. Both target seed question q-005 (geographic/KYC constraints) with identical 'read local files only, zero URL fetches' directives. q-103 has more comprehensive file-read instructions and the more explicit structural-conclusion requirement. Keeping both fragments synthesis effort.
- [2026-07-06T20:04:02+00:00] pipeline (cycle 77): read budget 12 truncated 76 candidates -> 12 selected (dropped: 47 after-budget (unclassified), 0 domain-cap, 15 per-query-cap, 0 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T20:04:12+00:00] pipeline (cycle 77): 0/12 useful reads for q-101 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T20:04:13+00:00] worker BLOCKED on q-101 (HARD, count=3): no useful reads: 12 URLs selected, 8 read but none useful, 4 fetch-failed
- [2026-07-06T20:08:25+00:00] evaluator (cycle 77) closed q-101 as immaterial: DEPRECATED in favor of the q-010 synthesis question opened in this cycle with stronger local-file-only instructions and explicit adjudicated premises. q-101 was hard-blocked in cycle 77 (worker fetched URLs despite no-fetch directive). The replacement question uses the same approach but with more explicit structural-constraint guidance (cross-platform arb impossible per q-018-c21) and clearer adjudicated premises.
- [2026-07-06T20:08:25+00:00] evaluator (cycle 77) closed q-102 as immaterial: DEPRECATED in favor of the q-003 synthesis question opened in this cycle with stronger local-file-only instructions. The replacement question includes explicit file paths, known data points to extract, and clearer output structure. Avoids fragmenting the same synthesis across two questions.
- [2026-07-06T20:08:25+00:00] evaluator (cycle 77) closed q-103 as immaterial: DEPRECATED in favor of the q-005 synthesis question opened in this cycle with stronger local-file-only instructions. The replacement question explicitly states the matrix structure, provides the conclusion (cross-platform arb impossible), and cites specific finding IDs and file paths for data extraction. Avoids fragmenting the same synthesis across two questions.
- [2026-07-06T20:08:42+00:00] pipeline (cycle 78): read budget 12 truncated 37 candidates -> 12 selected (dropped: 24 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 0 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T20:08:51+00:00] pipeline (cycle 78): 0/12 useful reads for q-107 (10 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T20:08:51+00:00] worker BLOCKED on q-107 (HARD, count=2): no useful reads: 12 URLs selected, 10 read but none useful, 2 fetch-failed
- [2026-07-06T20:11:45+00:00] evaluator (cycle 78) closed q-107 as immaterial: DEPRECATED. HARD BLOCKED in cycle 78 after worker fetched URLs despite ZERO-FETCH directive. Superseded by the new q-005 synthesis question opened in this evaluation cycle with stronger local-file-only instructions and explicit Read-tool file paths.
- [2026-07-06T20:11:45+00:00] evaluator (cycle 78) closed q-108 as immaterial: DEPRECATED. Near-duplicate of the new q-010 synthesis question opened in this evaluation cycle. The new version has stronger LOCAL-FILE-ONLY instructions with explicit Read-tool file paths, incorporates all three evaluator adjudications as settled premises, and explicitly states the structural impossibility of cross-platform arbitrage.
- [2026-07-06T20:11:45+00:00] evaluator (cycle 78) closed q-109 as immaterial: DEPRECATED. Near-duplicate of q-102 and q-105 (all target seed q-003). The q-003 spread/liquidity data needed to close this gap is partially documented in q-042-c35 (FalconX/Kaiko tiers), q-094-c67 (spread narrowing), and q-009-c08 (latency arb/Le 2026 half-life) — but repeated synthesis attempts have hard-blocked. Closing to avoid further fragmentation; the q-010 synthesis question will incidentally cover spread-cost data through the breakeven threshold analysis.
- [2026-07-06T20:11:55+00:00] pipeline (cycle 79): read budget 12 truncated 52 candidates -> 12 selected (dropped: 33 after-budget (unclassified), 0 domain-cap, 1 per-query-cap, 3 blocked, 3 already-seen, 0 invalid)
- [2026-07-06T20:12:04+00:00] pipeline (cycle 79): 0/12 useful reads for q-110 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T20:12:04+00:00] worker BLOCKED on q-110 (HARD, count=2): no useful reads: 12 URLs selected, 8 read but none useful, 4 fetch-failed
- [2026-07-06T20:16:16+00:00] evaluator (cycle 79) closed q-110 as immaterial: REDUNDANT. q-110 targets seed q-005 (geographic/KYC matrix) using local file reads. Now superseded by this evaluation cycle's determination that q-005 is substantially answered by existing findings (q-018-c21, q-011-c09, q-049-c42, q-004-c05). The geographic/KYC matrix is derivable from these findings without additional synthesis. Keeping q-110 open fragments effort across duplicate synthesis tasks targeting the same seed question.
- [2026-07-06T20:16:16+00:00] evaluator (cycle 79) closed q-111 as immaterial: REDUNDANT. q-111 targets seed q-010 (Facet 5: expected returns) using local file reads — identical scope to the new q-010 synthesis question opened in this cycle. The new version has more precise file paths, explicit adjudicated premises, and the structural-impossibility-of-cross-platform-arb constraint. Closing q-111 prevents two workers producing potentially inconsistent Facet 5 assessments.
- [2026-07-06T20:16:16+00:00] evaluator (cycle 79) closed q-112 as immaterial: REDUNDANT. q-112 targets amending the three contaminated findings (q-007-c06, q-035-c30, q-004-c05) — identical scope to the amendment question opened in this cycle. The new version has step-by-step instructions with explicit file paths and adjudicated premises. Closing q-112 avoids fragmenting the same amendment task across two questions.
- [2026-07-06T20:16:26+00:00] pipeline (cycle 80): read budget 12 truncated 54 candidates -> 12 selected (dropped: 41 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 1 blocked, 0 already-seen, 0 invalid)
- [2026-07-06T20:16:33+00:00] pipeline (cycle 80): 0/12 useful reads for q-113 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T20:16:34+00:00] worker BLOCKED on q-113 (HARD, count=2): no useful reads: 12 URLs selected, 8 read but none useful, 4 fetch-failed
- [2026-07-06T20:21:08+00:00] evaluator (cycle 80) closed q-113 as immaterial: DEAD END. q-113 asked to edit three contaminated findings (q-007-c06, q-035-c30, q-004-c05) using the Read/Edit tools on local files only. It was HARD BLOCKED in cycle 80 (worker fetched URLs despite ZERO-FETCH directive). The amendment task has been attempted through three different question formulations (q-091, q-092, q-093 consolidated into q-095, then q-112, then q-113) and all have either been hard-blocked or produced only a separate correction finding (q-095-c68) without editing the originals. The investigation infrastructure cannot execute file-editing tasks — the original contaminated findings will remain as-is and the correction exists in q-095-c68. Further attempts will consume budget without success.
- [2026-07-06T20:21:08+00:00] evaluator (cycle 80) closed q-114 as immaterial: DEAD END. q-114 asks to synthesize spread/liquidity data for q-003 using Read on local files only — identical scope to q-099, q-102, q-105, q-109 which have all been either hard-blocked or closed. The pattern is consistent: synthesis tasks directing workers to read local files invariably result in workers fetching URLs and getting hard-blocked. The investigation infrastructure assigns URLs to every task and workers cannot complete without trying them. Superseded by the new embedded-data synthesis question in this evaluation cycle which includes all q-003 data inline.
- [2026-07-06T20:21:08+00:00] evaluator (cycle 80) closed q-115 as immaterial: DEAD END. q-115 asks to synthesize expected returns for q-010 using Read on local files only — identical scope to q-100, q-101, q-104, q-108, q-111 which have ALL been hard-blocked, soft-blocked, or closed. q-100 was RETIRED after 5 hard blocks, q-101 was hard-blocked at cycle 77. The local-file-only synthesis pattern is structurally non-viable in this infrastructure. Superseded by the new embedded-data synthesis question in this evaluation cycle which provides all critical data points inline in the question text — removing the need for workers to discover data from local files.
- [2026-07-06T20:21:37+00:00] pipeline (cycle 81): read budget 12 truncated 61 candidates -> 12 selected (dropped: 30 after-budget (unclassified), 0 domain-cap, 16 per-query-cap, 0 blocked, 2 already-seen, 1 invalid)
- [2026-07-06T20:21:55+00:00] worker returned outcome=fragmented for q-116 with no child_questions (malformed decomposition); degraded to a soft block rather than crashing the run
- [2026-07-06T20:21:55+00:00] worker BLOCKED on q-116 (soft, count=1): worker said 'fragmented' but provided no child_questions (malformed decomposition)
- [2026-07-06T20:25:25+00:00] pipeline (cycle 82): read budget 12 truncated 38 candidates -> 12 selected (dropped: 24 after-budget (unclassified), 0 domain-cap, 0 per-query-cap, 0 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T20:25:29+00:00] read dedup (cycle 82): https://scholar.google.co.in/citations?user=ItpLDpAAAAAJ&hl=en carries duplicate content of already-read https://scholar.google.com/citations?user=ItpLDpAAAAAJ&hl=en; reader session skipped (soft dedup — the content was already read once this run; nothing dropped silently)
- [2026-07-06T20:25:36+00:00] pipeline (cycle 82): 0/12 useful reads for q-116 (9 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T20:25:37+00:00] worker BLOCKED on q-116 (HARD, count=3): no useful reads: 12 URLs selected, 9 read but none useful, 3 fetch-failed
- [2026-07-06T20:27:46+00:00] evaluator (cycle 82) closed q-116 as immaterial: RETIRED as exhausted scope after 4+ hard-blocked attempts. The Bürgi et al. primary paper at www2.gwu.edu/~forcpgm/2026-001.pdf has proven irretrievable (q-098 retired after 4 hard blocks, q-116 itself hard-blocked in cycle 82). The RePEc abstract [src-makers-and-takers-the-economics-of-the-k-2, credibility 95] confirms the paper exists but the PDF is inaccessible to the run's retrieval infrastructure. The investigation has exhausted every known resolution path: direct GWU URL, SSRN author search, arXiv, Google Scholar, ResearchGate, and EconPapers. The paper's existence and its likely contents (fee-adjusted returns per Substack summary) are documented in q-085-c62 as a limitation. Further attempts would consume remaining budget without probable return.
- [2026-07-06T20:27:46+00:00] evaluator (cycle 82) closed q-117 as immaterial: DIMINISHING RETURNS given remaining budget ($0.88 run spend, $2 evaluator budget). q-117 targets spread/liquidity data, ToS provisions, settlement disputes, and practitioner fee screenshots from third-party sources. Spread data is already fragmentarily documented in q-042-c35 and q-094-c67. ToS pages have been retired as exhausted scope after 6+ hard blocks. The structured embedded-data syntheses for q-003, q-005, and q-010 (opened above) provide more efficient paths to closure for the remaining seed questions. q-117's broad-scope search across multiple domains is likely to produce fragmented results that would require additional synthesis cycles to integrate — cycles the budget does not have.
- [2026-07-06T20:27:46+00:00] evaluator (cycle 82) hit question cap 120; dropped gap 'SYNTHESIS (EMBEDDED DATA — NO URL FETCHES — ALL DATA IS IN T'
- [2026-07-06T20:27:57+00:00] pipeline (cycle 83): read budget 12 truncated 38 candidates -> 12 selected (dropped: 18 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 2 blocked, 2 already-seen, 0 invalid)
- [2026-07-06T20:28:07+00:00] pipeline (cycle 83): 0/12 useful reads for q-118 (8 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T20:28:07+00:00] worker BLOCKED on q-118 (HARD, count=2): no useful reads: 12 URLs selected, 8 read but none useful, 4 fetch-failed
- [2026-07-06T20:31:36+00:00] evaluator (cycle 83) closed q-119 as immaterial: SUPERSEDED by the new embedded-data synthesis question for q-010 (Facet 5) opened in this evaluation cycle. q-119 targets the narrower seed question q-005 (geographic/KYC matrix) only, while the new synthesis covers ALL open seed questions. Closing avoids fragmenting synthesis effort across multiple questions.
- [2026-07-06T20:31:36+00:00] evaluator (cycle 83) closed q-120 as immaterial: SUPERSEDED by the new embedded-data synthesis question opened in this cycle and by the newly opened q-003 spread-focused retrieval question targeting the FalconX/Kaiko article at metamask.io. q-120 targets seed question q-003 (spreads/liquidity) with the same embedded-data approach that has proven non-viable (workers fetch URLs despite no-fetch directives). The new approach targets an independently-hosted source (metamask.io) for spread data rather than relying on local-file synthesis.
- [2026-07-06T20:31:37+00:00] evaluator (cycle 83) hit question cap 120; dropped gap 'SYNTHESIS (EMBEDDED DATA — DO NOT FETCH ANY URL — ALL DATA Y'
- [2026-07-06T20:31:49+00:00] worker: primary endpoint 'deepseek_flash' failed after retries (WorkerError); falling back to 'anthropic'/claude-haiku-4-5-20251001 to keep the run alive.
- [2026-07-06T20:32:55+00:00] pipeline (cycle 84): read budget 12 truncated 64 candidates -> 12 selected (dropped: 45 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 0 blocked, 5 already-seen, 0 invalid)
- [2026-07-06T20:33:10+00:00] pipeline (cycle 84): 0/12 useful reads for q-118 (5 read, none useful) — engine-blocked without compose (HARD)
- [2026-07-06T20:33:10+00:00] worker BLOCKED on q-118 (HARD, count=4): no useful reads: 12 URLs selected, 5 read but none useful, 7 fetch-failed
- [2026-07-06T20:33:22+00:00] evaluator: primary endpoint 'deepseek' failed after retries (EvalError); falling back to 'anthropic'/claude-sonnet-4-6 to keep the run alive.
- [2026-07-06T20:40:55+00:00] evaluator (cycle 84) RETIRED q-118 as exhausted scope after 4 blocked attempts — no reachable sources; recorded as a limitation, not answered (autonomous backstop, prevents the worker looping on it)
- [2026-07-06T20:41:07+00:00] worker: primary endpoint 'deepseek_flash' failed after retries (WorkerError); falling back to 'anthropic'/claude-haiku-4-5-20251001 to keep the run alive.
- [2026-07-06T20:42:23+00:00] pipeline (cycle 85): read budget 12 truncated 63 candidates -> 12 selected (dropped: 46 after-budget (unclassified), 0 domain-cap, 2 per-query-cap, 2 blocked, 1 already-seen, 0 invalid)
- [2026-07-06T20:42:38+00:00] pipeline (cycle 85): 0/12 useful reads for q-003 (2 read, none useful) — engine-blocked without compose (soft)
- [2026-07-06T20:42:39+00:00] worker BLOCKED on q-003 (soft, count=1): no useful reads: 12 URLs selected, 2 read but none useful, 10 fetch-failed
- [2026-07-06T20:42:51+00:00] evaluator: primary endpoint 'deepseek' failed after retries (EvalError); falling back to 'anthropic'/claude-sonnet-4-6 to keep the run alive.
- [2026-07-06T21:02:19+00:00] evaluator (cycle 85) hit question cap 120; dropped gap "Read the Le (2026) paper 'Decomposing Crowd Wisdom: Domain-S"
- [2026-07-06T21:02:31+00:00] worker: primary endpoint 'deepseek_flash' failed after retries (WorkerError); falling back to 'anthropic'/claude-haiku-4-5-20251001 to keep the run alive.
- [2026-07-06T21:03:31+00:00] pipeline (cycle 86): read budget 12 truncated 38 candidates -> 12 selected (dropped: 9 after-budget (unclassified), 0 domain-cap, 4 per-query-cap, 6 blocked, 7 already-seen, 0 invalid)
- [2026-07-06T21:03:47+00:00] pipeline (cycle 86): 0/12 useful reads for q-003 (1 read, none useful) — engine-blocked without compose (soft)
- [2026-07-06T21:03:48+00:00] worker BLOCKED on q-003 (soft, count=2): no useful reads: 12 URLs selected, 1 read but none useful, 11 fetch-failed
- [2026-07-06T21:04:00+00:00] evaluator: primary endpoint 'deepseek' failed after retries (EvalError); falling back to 'anthropic'/claude-sonnet-4-6 to keep the run alive.
- [2026-07-06T21:12:55+00:00] evaluator (cycle 86) hit question cap 120; dropped gap 'Produce a standalone closure finding for seed question q-005'
- [2026-07-06T21:12:56+00:00] verification wave halted: budget breaker reached (6 findings left unverified)
- [2026-07-06T21:13:08+00:00] synthesizer: primary endpoint 'deepseek' failed after retries (SynthesisError); falling back to 'anthropic'/claude-sonnet-4-6 to keep the run alive.
- [2026-07-06T21:20:03+00:00] synthesizer attempt 1/3: cited non-existent source ids ['src-prediction-markets-are-turning-into-a-bot']; retrying with feedback
- [2026-07-06T21:20:15+00:00] synthesizer: primary endpoint 'deepseek' failed after retries (SynthesisError); falling back to 'anthropic'/claude-sonnet-4-6 to keep the run alive.

## Source registry

- `src-5-cent-spreads-in-prediction-markets-liq` — 5-cent spreads in prediction markets: liquidity, costs, and trading signals (web, credibility 75): https://metamask.io/news/5-cent-spread-prediction-markets
- `src-adverse-selection-in-prediction-markets` — Adverse Selection in Prediction Markets: Evidence from Kalshi (paper, credibility 90): https://law.stanford.edu/publications/adverse-selection-in-prediction-markets-evidence-from-kalshi/
  > "Using 41.6 million trades, we measure adverse selection in prediction markets."
  > "traders systematically overbet YES in markets that predominantly settle NO, generating a behavioral surplus that cross-subsidizes adverse selection."
- `src-ai-prediction-market-case-studies-6-impl` — AI Prediction Market Case Studies: 6 Implementations That Worked (web, credibility 50): https://interexy.com/ai-prediction-market-case-studies-implementations
  > "A single confidently-wrong settlement on a $5K position takes out half the bankroll."
  > "If the system trades, it can be gamed. If it resolves, it can be poisoned. If it monitors, it can be evaded."
- `src-bank-deposits` — Bank Deposits (web, credibility 90): https://help.kalshi.com/en/articles/13823798-bank-deposits
- `src-best-kalshi-trading-bots-on-github-2026` — Best Kalshi Trading Bots on GitHub (2026 Open-Source) (web, credibility 50): https://www.alphascope.app/blog/kalshi-trading-bot-github
  > "Kalshi enforces rate limits. Your bot needs to respect them or risk getting temporarily blocked"
  > "Limit orders and market orders. Limit orders are strongly recommended for bots"
- `src-best-prediction-market-apis-for-develope` — Best Prediction Market APIs for Developers: Complete Guide (web, credibility 40): https://newyorkcityservers.com/blog/best-prediction-market-apis
  > "Kalshi provides a full sandbox at demo-api.kalshi.com."
- `src-card-deposits` — Card Deposits (web, credibility 80): https://help.kalshi.com/en/articles/13823795-card-deposits
- `src-cftc-and-kalshi-announce-enforcement-act` — CFTC and Kalshi Announce Enforcement Actions Targeting Prediction Markets (web, credibility 85): https://www.lowenstein.com/news-insights/publications/client-alerts/cftc-and-kalshi-announce-enforcement-actions-targeting-prediction-markets-fctm
- `src-cftc-orders-event-based-binary-options-m` — CFTC Orders Event-Based Binary Options Markets Operator to Pay $1.4 Million Penalty (web, credibility 95): https://www.cftc.gov/PressRoom/PressReleases/8478-22
  > "The order requires that Polymarket pay a $1.4 million civil monetary penalty, facilitate the resolution (i.e. wind down) of all markets displayed on Polymarket.com that do not comply with the Commodity Exchange Act (CEA) and applicable CFTC regulations, and cease and desist from violating the CEA and CFTC regulations, as charged."
  > "The order further finds that Polymarket has offered more than 900 separate event markets since its inception, while deploying smart contracts hosted on a blockchain to operate the markets."
- `src-clob-client` — clob-client (web, credibility 85): https://github.com/Polymarket/clob-client
- `src-connectivity-kalshi-fix-api-documentatio` — Connectivity — Kalshi FIX API Documentation (web, credibility 95): https://docs.kalshi.com/fix/connectivity
  > "Only one FIX connection is allowed per API key. Separate API keys are required for concurrent connections."
  > "FIX application messages use the same token model, token costs, and Read/Write buckets as the equivalent REST API operations."
  > "Mass Cancel Request (35=q) is limited to 1 request/second."
- `src-create-order-kalshi-api-documentation` — Create Order | Kalshi API Documentation (web, credibility 90): https://docs.kalshi.com/margin-rest/orders/create-order
  > "Specifies whether the order place count should be capped by the member's current position. Orders with reduce_only set to true will be rejected unless time_in_force is immediate_or_cancel or fill_or_kill."
- `src-create-order-v2-kalshi-api-documentation` — Create Order (V2) - Kalshi API Documentation (web, credibility 90): https://docs.kalshi.com/api-reference/orders/create-order-v2
- `src-creating-and-using-a-demo-account` — Creating and using a demo account (web, credibility 80): https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account
  > "Kalshi's demo environment lets you explore the platform and practice trading using mock funds."
  > "Your demo account credentials are completely separate from your production account credentials, so your financial and personal data stay secure."
  > "Nothing you do in the demo environment affects your production account."
- `src-decomposing-crowd-wisdom-domain-specific` — Decomposing Crowd Wisdom: Domain-Specific Calibration Dynamics in Prediction Markets (paper, credibility 85): https://arxiv.org/html/2602.19520v1
  > "The dominant pattern is persistent underconfidence in political markets, where prices are chronically compressed toward 50%, and this bias generalises across both exchanges."
  > "At long horizons, markets systematically understate the probability of the favoured outcome: a contract trading at 70 cents one month out corresponds to a true probability closer to 75%."
- `src-favorite-longshot-bias` — Favorite-Longshot Bias (web, credibility 60): https://predictionpilot.io/blog/favorite-longshot
  > "The edge is typically small — on the order of 1-3% per trade — which means fees, execution quality, and volume of trades all matter significantly."
  > "Page and Clemen (2013) examined InTrade and the Iowa Electronic Markets and found that contracts above 80 cents were slightly better calibrated than contracts below 20 cents, but mispricing persisted at the extremes."
- `src-fee-schedule-for-july-2025-7-8-25-update` — Fee Schedule for July 2025 - 7.8.25 Update (page_capture, credibility 85): https://web.archive.org/web/20250708150126/https://kalshi.com/docs/kalshi-fee-schedule.pdf
- `src-fix-order-entry-kalshi-api-documentation` — FIX Order Entry — Kalshi API Documentation (web, credibility 90): https://docs.kalshi.com/fix-margin/order-entry
- `src-galaxy-deep-research-report-how-hyperliq` — Galaxy Deep Research Report: How Hyperliquid's HIP-4 Upgrade Changes the Landscape of Prediction Markets? (web, credibility 85): https://www.weex.com/news/detail/galaxy-deep-research-report-how-hyperliquids-hip-4-upgrade-changes-the-landscape-of-prediction-markets-nxnsl75eanr99yoglh68dpye
  > "HIP-4 charges zero fees for opening positions. Fees are only charged when closing, destroying, or settling. (In fact, during the initial testing phase, all outcome market fees are zero.)"
  > "For traders, predicting the future on Hyperliquid is much more economical than on Polymarket and Kalshi, which charge significantly higher fees on winning positions."
  > "Polymarket collected $47.7 million in fees in April."
- `src-get-balance` — Get Balance (web, credibility 85): https://docs.kalshi.com/margin-rest/portfolio/get-balance
- `src-get-perps-account-api-limits` — Get Perps Account API Limits (web, credibility 90): https://docs.kalshi.com/margin-rest/account/get-perps-account-api-limits
- `src-health-api-overview-polymarket-us-docume` — Health API Overview | Polymarket US Documentation (web, credibility 75): https://docs.polymarket.us/institutional/health/overview
- `src-how-courts-and-regulators-are-redefining` — How Courts and Regulators Are Redefining U.S. Prediction Markets (web, credibility 60): https://darroweverett.com/prediction-markets-future-legal-analysis-cftc-state-laws/
  > "The most consequential recent decision arrived on April 6, 2026, when the United States Court of Appeals for the Third Circuit affirmed a preliminary injunction for Kalshi against New Jersey, holding that Kalshi showed a reasonable chance of success in arguing that the CEA preempts state gambling law as applied to CFTC‑regulated event contracts."
  > "The CFTC ramped up the federal-state clash by suing Arizona, Connecticut, and Illinois in April 2026 to stop what it has characterized as unlawful state interference with federally regulated event markets, reflecting a more assertive federal posture on preemption."
- `src-how-kalshi-and-polymarket-settle-event-c` — How Kalshi and Polymarket Settle Event Contracts (and Disputes) (web, credibility 75): https://defirate.com/prediction-markets/how-contracts-settle/
- `src-how-to-build-a-prediction-market-trading` — How to Build a Prediction Market Trading Bot: A Practical API Guide (web, credibility 60): https://www.predictionhunt.com/blog/how-to-build-prediction-market-trading-bot-api-guide
  > "Fourteen of the top twenty most profitable wallets on Polymarket are bots."
  > "A bot that tries to deploy $10,000 into one of these markets will move the price against itself so badly that the theoretical edge vanishes before the order is fully filled."
- `src-is-polymarket-legal-in-2026` — Is Polymarket Legal in 2026? (web, credibility 50): https://news.dropstab.com/research/is-polymarket-legal
  > "Polymarket Global has been geo-blocked from US users since the January 2022 CFTC settlement."
- `src-is-polymarket-legal-in-the-us-yes-open-o` — Is Polymarket Legal in the US? Yes — Open on iOS (Updated June 2026) (web, credibility 45): https://startpolymarket.com/countries/united-states/
  > "Polymarket US is CFTC-regulated, requires full KYC (government ID, SSN), and is funded through registered futures commission merchants. The international exchange has no KYC, accepts direct crypto deposits, and has significantly more liquidity and market variety."
- `src-is-polymarket-legal-in-the-usa-2026-upda` — Is Polymarket Legal in the USA? (2026 Update) (web, credibility 55): https://cloudaffi.com/us/guides/is-polymarket-legal
  > "The Services are not available to persons or entities who reside in, are located in, are incorporated in, or have a registered office in the United States of America or any Prohibited Localities."
  > "There are NO US states where Polymarket is currently legal."
- `src-kalshi-api-the-complete-developer-s-guid` — Kalshi API: The Complete Developer's Guide (web, credibility 45): https://dev.to/zuplo/kalshi-api-the-complete-developers-guide-1fo4
  > "Kalshi uses tokens that expire every 30 minutes, so your code needs to handle periodic re-login to maintain active sessions"
- `src-kalshi-fees-how-much-does-kalshi-charge` — Kalshi Fees: How Much Does Kalshi Charge Per Contract & What is the Fee Schedule? (web, credibility 30): https://sailgp.com/prediction-markets/kalshi/fees
  > "Kalshi trading fees = round up(0.07 x C x P x (1-P))"
  > "Kalshi maker fees = round up(0.0175 x C x P x (1-P))"
- `src-kalshi-review-june-2026-real-money-test` — Kalshi Review (June 2026): Real Money Test of the CFTC-Regulated Exchange (web, credibility 60): https://tech-insider.org/prediction-markets/platforms/kalshi-review/
  > "There are no fees on funding (ACH or debit deposits are free). Withdrawal fees: ACH is free, wire is $25 outbound."
  > "Across our 5-withdrawal test protocol, the median ACH withdrawal completed in 18 hours, ranging from 14 to 22 hours for amounts between $250 and $4,500. Wire transfer of $7,000 completed in 26 hours. Zero failed or held requests, no withdrawal-triggered KYC re-verification."
  > "Deposit confirmation in our test was reliable across all methods. ACH funded within 1 hour for all test deposits. Debit card credits were instant."
- `src-kalshi-vs-polymarket-a-side-by-side-comp` — Kalshi vs. Polymarket: A Side-by-Side Comparison of Legality, Access, and Trading (web, credibility 60): https://www.si.com/prediction-markets/reviews/kalshi-vs-polymarket
  > "Kalshi's strict $25,000 retail position limits against Polymarket's deeper liquidity pools, which better accommodate institutional-sized orders."
- `src-kalshi-vs-polymarket-how-to-arbitrage-pr` — Kalshi vs Polymarket: How to Arbitrage Prediction Markets in 2026 (web, credibility 50): https://clawarbs.com/blog/kalshi-vs-polymarket-arbitrage/
- `src-kalshi-vs-polymarket-operator-affiliate` — Kalshi vs Polymarket: Operator & Affiliate Comparison 2026 (web, credibility 45): https://track360.io/blog/kalshi-vs-polymarket-operator-comparison-2026
  > "Resolution determines which contracts pay out and which expire worthless, and it is one of the sharpest differences between the two. On Kalshi, resolution follows the exchange's published contract terms and a defined data source, with the exchange responsible for declaring the result. On Polymarket, resolution runs through the UMA optimistic oracle, which proposes an outcome that becomes final unless someone disputes it within a challenge window."
  > "One model trades regulatory clarity and US legality for a closed, permissioned perimeter; the other trades global, permissionless access for on-chain settlement risk."
  > "Oracle risk is a real operator consideration"
- `src-liquidity-incentive-program-polymarket-u` — Liquidity Incentive Program — Polymarket US Documentation (web, credibility 80): https://docs.polymarket.us/incentives/liquidity
  > "This program rewards traders for placing resting limit orders. The closer your orders are to the best price and the larger they are, the more you earn."
- `src-liquidity-rewards` — Liquidity Rewards (web, credibility 85): https://help.polymarket.com/en/articles/13364466-liquidity-rewards
- `src-liquidity-rewards-polymarket-documentati` — Liquidity Rewards — Polymarket Documentation (web, credibility 85): https://docs.polymarket.com/market-makers/liquidity-rewards
  > "Each market configures a max spread and min size cutoff within which orders are considered."
- `src-makers-and-takers-the-economics-of-the-k` — Makers and Takers: The Economics of the Kalshi Prediction Market (paper, credibility 90): https://ideas.repec.org/p/gwc/wpaper/2026-001.html
- `src-makers-and-takers-the-economics-of-the-k-2` — Makers and Takers: The Economics of the Kalshi Prediction Market (paper, credibility 95): https://econpapers.repec.org/RePEc:gwc:wpaper:2026-001
  > "Starting in 2021, Kalshi was the first federally licensed prediction market in the United States and remains the dominant platform in this segment. Using transaction-level data on over 300,000 contracts, we provide the first systematic evidence on its pricing."
- `src-market-data-kalshi-api-documentation` — Market Data — Kalshi API Documentation (web, credibility 80): https://docs.kalshi.com/fix/market-data
  > "Scheduled (time-based) opens and closes are not emitted as discrete events and are not reported here."
- `src-order-entry-management-and-best-practice` — Order entry, management, and best practices for market makers (web, credibility 80): https://docs.polymarket.com/market-makers/trading
- `src-polymarket-agents` — Polymarket Agents (web, credibility 70): https://github.com/Polymarket/agents/
- `src-polymarket-blocks-vpns-and-tightens-iden` — Polymarket blocks VPNs and tightens identity verification as over 30 countries ban the betting platform (web, credibility 65): https://www.techradar.com/vpn/vpn-privacy-security/polymarket-blocks-vpns-and-tightens-identity-verification-as-over-30-countries-ban-the-betting-platform
  > "Polymarket is clamping down on VPN users who bypass geographic blocks"
- `src-polymarket-fees-2026-calculator-complete` — Polymarket Fees 2026: Calculator & Complete Cost Guide (web, credibility 45): https://www.predictionhunt.com/blog/polymarket-fees-complete-guide
  > "US traders on the regulated exchange pay a flat 0.30% taker fee with a 0.20% maker rebate. Limit orders (maker orders) are free on both platforms."
  > "Polymarket charges taker fees on nearly every market category: Crypto 1.80%, Economics 1.50%, Mentions 1.56%, Culture 1.25%, Weather 1.25%, Finance 1.00%, Politics 1.00%, Tech 1.00%, and Sports 0.75%."
- `src-polymarket-kalshi-trading-bot-automate-p` — Polymarket & Kalshi Trading Bot: Automate Prediction Market Trading (web, credibility 40): https://clawarbs.com/blog/prediction-market-trading-bot/
  > "Buy YES on Kalshi at 42¢ + buy NO on Polymarket at 0.53. Total cost: $0.95. Guaranteed payout: $1.00. Profit: $0.05 per contract (5.3% edge before fees)."
  > "Prediction market contracts lock up capital until resolution. A $100 position on a contract that resolves in 30 days ties up that $100 for a month."
- `src-polymarket-py-clob-client` — Polymarket/py-clob-client (web, credibility 90): https://github.com/Polymarket/py-clob-client
  > "You only need to set these once per wallet. After that, you can trade freely."
- `src-polymarket-receives-cftc-approval-of-ame` — Polymarket Receives CFTC Approval of Amended Order of Designation, Enabling Intermediated U.S. Market Access (web, credibility 70): https://www.prnewswire.com/news-releases/polymarket-receives-cftc-approval-of-amended-order-of-designation-enabling-intermediated-us-market-access-302625833.html
  > "the U.S. Commodity Futures Trading Commission ("CFTC") has issued an Amended Order of Designation, permitting Polymarket to operate an intermediated trading platform subject to the full set of requirements applicable to federally regulated U.S. exchanges."
  > "Polymarket remains subject to all provisions of the Commodity Exchange Act and applicable CFTC regulations governing Designated Contract Markets, including self-regulatory obligations."
  > "Polymarket will implement additional rules, policies, and processes applicable to intermediated trading prior to official launch."
- `src-polymarket-vs-kalshi-how-the-world-s-two` — Polymarket vs. Kalshi: How The World's Two Biggest Prediction Markets Compare (web, credibility 65): https://info.arkm.com/research/polymarket-vs-kalshi-how-the-worlds-two-biggest-prediction-markets-compare
  > "Since Kalshi accepts deposits via traditional fiat rails, it also levies a 2% processing fee on debit card deposits and withdrawals, though ACH transfers are free."
- `src-prediction-market-settlement-rules-avoid` — Prediction Market Settlement Rules: Avoid Fake Arbitrage and Resolution Traps (web, credibility 45): https://www.alphascope.app/blog/prediction-market-settlement-rules
  > "Fake arbitrage appears when traders compare two prices without comparing two rulebooks. A scanner can surface candidate gaps, but the trader still has to verify that both legs are actually equivalent."
  > "Kalshi markets are regulated event contracts with defined settlement procedures. Polymarket markets often rely on market-specific resolution criteria and oracle-style processes. Both can be useful, but the rules may not match even when the event theme is the same."
  > "Common fake-arb patterns include similar political markets with different date cutoffs, crypto bills where one market resolves on passage and another on signature, sports props that use different official data sources, and macro contracts that use different release revisions."
- `src-prediction-markets-are-turning-into-a-bo` — Prediction Markets Are Turning Into a Bot Playground (web, credibility 60): https://www.financemagnates.com/trending/prediction-markets-are-turning-into-a-bot-playground/
  > "Wallet 0x8dxd reportedly turned roughly $300 into more than $400,000 within a month trading ultra-short crypto prediction contracts."
- `src-rate-limits-and-tiers` — Rate Limits and Tiers (web, credibility 95): https://docs.kalshi.com/getting_started/rate_limits
  > "Kalshi may, at its discretion, adjust your tier at any time, including downgrading you from higher tiers following prolonged inactivity."
- `src-research-review-24-april-2026-prediction` — Research Review | 24 April 2026 | Prediction Markets (web, credibility 45): https://www.capitalspectator.com/research-review-24-april-2026-prediction-markets/
  > "Trader skill, not the maker-taker distinction, determines who profits in prediction markets."
- `src-semantic-non-fungibility-and-violations` — Semantic Non-Fungibility and Violations of the Law of One Price in Prediction Markets (paper, credibility 90): http://arxiv.org/abs/2601.01706
  > "semantically equivalent markets exhibit persistent execution-aware price deviations of 2-4% on average, even in highly liquid and information-rich settings"
  > "These mispricings give rise to persistent cross-platform arbitrage opportunities driven by structural frictions rather than informational disagreement."
- `src-the-ai-superforecasters-are-here` — The AI Superforecasters Are Here (web, credibility 75): https://www.astralcodexten.com/p/the-ai-superforecasters-are-here
  > "Plenty of people beat prediction markets. But it might take them several hours to figure out which markets have untapped alpha, several more hours to make a model and decide who to bet on at what probability, et cetera, and then they can only put in a few thousand dollars before the inefficiency is corrected and they need to move on to something else."
- `src-the-anatomy-of-a-blockchain-prediction-m` — The Anatomy of a Blockchain Prediction Market: Polymarket in the 2024 U.S. Presidential Election (paper, credibility 85): http://arxiv.org/abs/2603.03136
  > "Naive aggregation reports $958M of October Trump-market volume, compared with $391M under our decomposition."
  > "During October's large-account episode, capital flowed into both sides simultaneously, consistent with heterogeneous-beliefs trading rather than one-sided manipulation."
- `src-the-microstructure-of-wealth-transfer-in` — The Microstructure of Wealth Transfer in Prediction Markets (paper, credibility 75): https://jbecker.dev/research/prediction-market-microstructure
  > "At a price of 1 cent, a YES contract carries a historical expected value of -41%; buyers lose nearly half their capital in expectation. Conversely, a NO contract at the same 1-cent price delivers a historical expected value of +23%."
- `src-the-microstructure-of-wealth-transfer-in-2` — The Microstructure of Wealth Transfer in Prediction Markets (web, credibility 70): https://www.jbecker.dev/research/prediction-market-microstructure
- `src-trading-fees-on-polymarket` — Trading Fees on Polymarket (web, credibility 90): https://docs.polymarket.com/trading/fees
  > "Polymarket does not charge fees or profit from trading activity on these markets."
- `src-trading-on-the-polymarket-clob` — Trading on the Polymarket CLOB (web, credibility 85): https://docs.polymarket.com/trading/overview
  > "We recommend using the open-source SDK clients, which handle order signing, authentication, and submission"
- `src-what-five-new-academic-papers-say-about` — What Five New Academic Papers Say About Prediction Markets (web, credibility 60): https://nexteventhorizon.substack.com/p/what-five-new-academic-papers-say-prediction-markets
  > "the prices also display a systematic favorite-longshot bias. Contracts with low prices win less than required for them to break even on average, while the opposite applies to contracts with high prices."
  > "investors who buy contracts costing less than 10c lose over 60 percent of their money. In contrast, there is statistically significant evidence that contracts with prices above 50c earn a small positive rate of return."
  > "We use data from over 300,000 Kalshi contracts to show these predictions are supported by the evidence."
- `src-what-is-polymarket-us` — What is Polymarket US? (web, credibility 80): https://docs.polymarket.us/getting-started/what-is-polymarket-us
  > "Polymarket US is a CFTC-regulated exchange for trading event contracts on real-world outcomes."
- `src-when-should-a-market-maker-refuse-a-bet` — When should a market maker refuse a bet? (web, credibility 85): https://msande.stanford.edu/research-impact/mse-student-research/mse-senior-projects/2026-senior-projects/when-should-market
  > "Our project focused on addressing the challenge of adverse selection in prediction markets, where market makers risk trading against participants who possess superior or faster information."
  > "Backtesting results showed that trades flagged by the detector were associated with significantly larger subsequent price movements than unflagged trades, suggesting that the model successfully identifies situations where adverse selection risk is elevated."
  > "One challenge we encountered was that prediction markets differ widely in trading frequency and liquidity, meaning a model tuned for one market could perform poorly in another."
- `src-you-can-make-free-money-on-polymarket-if` — You Can Make Free Money on Polymarket. If You Know Math. (web, credibility 85): https://www.nytimes.com/interactive/2026/06/12/upshot/kalshi-polymarket-prediction-markets-arbitrage.html
  > "The probability spread of around five percentage points, minus Kalshi’s transaction fee."
  > "One-tenth of the top one percent of accounts on Polymarket rake in more than two-thirds of the profits"
