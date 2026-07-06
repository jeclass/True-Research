# Prediction-markets head-to-head — full scorecard (2026-07-06)

Blind label mapping (revealed): **Report A = Claude · Report B = Gemini · Report C = True Research.**
Reports anonymised (system names redacted) before merit judging; citation
auditors worked on the real reports (they must fetch real URLs). Two merit
judges scored independently; three auditors each sampled ~8 load-bearing
quantitative claims and fetched the cited sources.

## Objective metrics

| System | Words | Registry citations | URL refs | Cost | Posture |
|---|---|---|---|---|---|
| True Research | 21,025 | 208 (→107-source registry) | 95 | $11.03 | cheap (DeepSeek volume + Opus gate), budget-capped |
| Claude | ~4,200 | cited by name (papers/filings) | 2 | hosted | — |
| Gemini | ~5,700 | mixed inline | 44 | hosted | — |

## Merit judge scores (/10 per axis, /50 total)

**Judge 1 (straight rubric):**

| Axis | Claude | Gemini | True Research |
|---|---|---|---|
| Citation accuracy/specificity | 9 | 3 | 9 |
| Intellectual honesty | 9 | 2 | 10 |
| Depth/coverage (caveated) | 10 | 7 | 8 |
| Source quality | 8 | 2 | 9 |
| Actionability | 10 | 5 | 7 |
| **Total** | **46** | **19** | **43** |

**Judge 2 (skeptic; did own live fee-schedule verification):**

| Axis | Claude | Gemini | True Research |
|---|---|---|---|
| Citation accuracy/specificity | 9 | 4 | 8 |
| Intellectual honesty | 9 | 2 | 10 |
| Depth/coverage (caveated) | 9 | 6 | 8 |
| Source quality | 8 | 3 | 8 |
| Safety/actionability | 9 | 3 | 9 |
| **Total** | **44** | **18** | **43** |

Both judges: **Claude 1st, True Research 2nd (razor-thin), Gemini 3rd.** Both
scored True Research highest on intellectual honesty (10/10) and named it the
skeptic's "trust with capital" pick.

## Citation audit (sources fetched and checked against claims)

| System | Sampled | SUPPORTED | PARTIAL | SOURCE-DEAD | FABRICATED/MISCITED |
|---|---|---|---|---|---|
| Claude | 8 | 8 | 0 | 0 | **0** |
| True Research | 8 | 6 | 1 (Polymarket fee unit-label) | 1 (NYT paywall) | **0** |
| Gemini | 10 | 9 | 1 (unsourced pagination cap) | 0 | **0** |

Notable audit findings:
- **Claude:** every named paper resolved (arXiv:2508.03474 matched the $39.6M
  arbitrage figure to the dollar; CFTC PR 8478-22, WSJ quotes verbatim). Two
  cosmetic slips ("Makers *and* Takers" written as "or"; "$2.5B" for "$2.4B").
- **True Research:** read-gate excerpts matched live pages on all 7 checkable
  claims; Becker microstructure numbers and Bürgi −22%-after-fees "check out to
  the decimal." One real defect: Polymarket `feeRate` coefficient written with a
  `%` suffix (correct number, wrong unit — implies 0.07% vs the real ~1.75-1.80%
  effective peak).
- **Gemini:** the blind judges suspected fabricated API infrastructure; the
  auditor found the citations are *real and reachable* (9/10 supported). Real
  weakness is source tier (TRM Labs, Bleap, tradingvps, Medium) and presenting a
  Medium-blog "78-85% win rate" as fact. One unsupported detail (a "1,000 results
  per request" cap attributed to a Kalshi doc that doesn't state it).

## Headline

True Research (open-source, ~$11 cheap posture, budget-truncated) placed **2nd of
3**, statistically co-equal with **Claude** (frontier hosted) on trustworthiness,
**won the intellectual-honesty axis outright** against both frontier products,
and beat **Gemini** decisively. No system fabricated citations. The gap to 1st
is completeness, addressable with a larger budget/`--accurate` posture.
