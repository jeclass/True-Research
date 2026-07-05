# Evidence

Real end-to-end runs of True Research, with cost, scale, and — importantly —
where the engine *declined* to answer rather than fabricate. Every run below
lives on the operator's machine as a full `runs/<id>/` folder (gitignored:
reports contain large amounts of third-party page text); the figures come
straight from each run's `run.json` and `ledger.json`.

This document makes a deliberately **falsifiable** case. The claim is not "it's
always right" — it's "every claim is traceable, load-bearing claims are
adversarially checked, and the engine is honest about what it couldn't source."

## Run 1 — Amazon advertising strategy (hard, applied, `--cheap`)

**Question:** a senior-strategist-grade prompt for a prioritized, execution-ready
Amazon Ads strategy for one premium supplement SKU, anchored to June 2026, with
strict format and reversibility/automation constraints.

**Invocation:** `--cheap --gate opus --comprehensive --verify` (DeepSeek V4
volume tier, Opus 4.8 terminal gate, adversarial verification on).

| Metric | Value |
|---|---|
| Outcome | `conclusive` (evaluator passed, Opus gate confirmed) |
| Cost | **$4.65** |
| Cycles | 24 |
| Pages fetched + read | **323** |
| Sources kept (deduped, read-gated) | **97** |
| Findings | 13 |
| Report | ~14,600 words, 231 `[src-…]` citations, all resolving |

**What it demonstrates:**
- Deep, cheap, and cited: a 300+ page-read, verified report for under $5.
- **Honesty under thin evidence:** on niche sub-questions with no primary sources
  (e.g. supplement-specific SP bid mechanics), the verifier returned UNVERIFIED
  and the report flagged them as needing the operator's own data — it did not
  invent benchmarks.
- **Resilience:** DeepSeek returned an error at the synthesis step; the endpoint
  fallback fired and completed the report on Sonnet rather than dying.

## Run 2 — v1.0 release certification (all-Anthropic default, fresh clone)

**Question:** "What does current evidence say about creatine supplementation for
cognitive function in older adults?"

**Invocation:** a clean `git clone`, `pip install -e ".[dev]"`, a `.env`
containing **only** an `ANTHROPIC_API_KEY`, then `true-research run "…"
--max-budget-usd 2 --max-wall-hours 0.5`. This was the fresh-clone smoke that
certified the v1.0 engine.

| Metric | Value |
|---|---|
| Outcome | `budget` (stopped cleanly at the $2 cap) |
| Cost | $2.27 (the $0.27 over is the post-breaker synthesizer writing the partial report — by design) |
| Cycles | 4 |
| Report | cited `REPORT.md` (18 resolving `[src-…]`) + `REPORT.pdf`, zero tracebacks |
| Search | DuckDuckGo fallback (no search key configured) |

**What it demonstrates:** the out-of-the-box experience with a single API key and
no other setup produces a real, cited report + PDF; the budget breaker stops the
run cleanly and the synthesizer still ships a partial; one sub-question was
blocked honestly rather than fabricated.

## Run 3 — Amazon image/visual-brand strategy (resilience under real failures)

**Question:** a 7-part senior-strategist brief (main-image CTR, slot-by-slot
image stack, A+/Brand Story, demographic design language, mobile/OCR rules,
2025–26 platform changes, DSHEA compliance) for a premium longevity supplement,
with an explicit instruction to flag conclusions needing first-party data.

**Invocation:** `--cheap --gate opus --comprehensive --verify` — but this run's
value is what went wrong and what the engine did about it.

| Metric | Value |
|---|---|
| Outcome | `budget` (breaker-bounded; 55/56 questions resolved when it fired) |
| Cost | $11.84 total (~$6.40 of it an all-Anthropic detour, see below) |
| Cycles | 45 |
| Report | **13,774 words, 250 `[src-…]` citations**, all resolving |

**What it demonstrates — every failure hit a designed guardrail:**
- **Provider ran out of credit mid-run:** DeepSeek returned HTTP 402; judgment
  roles auto-fell back to Anthropic, and after 3 cycles of failed reads the
  read-outage breaker ended the run honestly at $0.50 instead of burning budget
  blind. Resumed on all-Anthropic, later resumed back to DeepSeek after top-up —
  same run, same state, three postures.
- **Refused to fabricate:** the brief demanded published supplement-category
  heatmap/CTR data that largely doesn't exist publicly; workers blocked with
  "answering would require fabrication" rather than dressing up low-credibility
  blogs, and the evaluator retired those questions as recorded limitations.
- **Refused to ship an uncited report:** one synthesis attempt produced a
  citation-free draft; the engine rejected it (invariant 3) rather than emitting
  it. (This incident drove the synthesizer self-heal ladder now in the engine.)

## Run 4 — v1.1 clone-and-go certification (zero-`.env`, keys via dashboard)

A clean `git clone` from the public GitHub repo → `pip install -e ".[dev]"` →
**312/312 tests pass** → `true-research ui` with **no `.env` file at all** →
all three API keys onboarded through the Keys panel (which created `.env`
itself; values never displayed) → a live distill preview → a Quick run launched
from the UI → **finished with a cited report, $0.32**, downloaded as both
markdown and PDF through the new endpoints. The entire out-of-the-box path a
stranger follows, certified end-to-end on the day the repo went public.

## Head-to-head vs hosted deep-research services

The True Research side is **complete** (both runs 2026-07-02, `--cheap --gate
opus --comprehensive --verify`):

| Question | Cost | Cycles | Report | Sources kept |
|---|---|---|---|---|
| GLP-1 RAs for weight loss, non-diabetic adults (2023–26 RCT evidence) | **$2.05** | 24 | 12,843 words, 208 citations | 101 |
| Local LLMs on consumer hardware, mid-2026 | **$2.39** | 23 | 14,736 words, 357 citations | 146 |

The exact prompts and collection/scoring protocol live in
[`docs/evidence/head-to-head/`](docs/evidence/head-to-head/): competitor outputs
(ChatGPT / Gemini Deep Research on the identical prompts) are scored blind on
citation accuracy, verification, depth, and source quality by a fresh Opus
judge whose spend is ledgered separately. Results land here when the competitor
outputs are collected.

## Reproducing

Every run is one command (see the [README](README.md)). Cost and scale figures
are read directly from `runs/<id>/ledger.json` and `run.json`. The engine's test
suite (317 tests, Linux + Windows, Python 3.11 & 3.13) runs fully offline.
