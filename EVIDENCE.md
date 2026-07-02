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

## Head-to-head vs hosted deep-research services

*(In progress.)* Two cross-domain questions are being run under True Research for
a like-for-like comparison against hosted deep-research (e.g. ChatGPT / Gemini
Deep Research) on the same prompts:

1. **Scientific:** efficacy & safety of GLP-1 receptor agonists for weight loss
   in adults without type-2 diabetes (2023–2026 peer-reviewed evidence).
2. **Technical:** the practical state of running LLMs locally on consumer
   hardware as of mid-2026.

The comparison will be scored blind on citation accuracy (do cited sources
support the claim?), verification (are load-bearing claims independently
checked?), depth, and source quality, with the full True Research reports
committed here alongside the competitor outputs. This section will be filled in
when those runs complete and the competitor outputs are collected.

## Reproducing

Every run is one command (see the [README](README.md)). Cost and scale figures
are read directly from `runs/<id>/ledger.json` and `run.json`. The engine's test
suite (288 tests, Linux + Windows, Python 3.11 & 3.13) runs fully offline.
