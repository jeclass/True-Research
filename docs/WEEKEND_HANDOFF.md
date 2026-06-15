# Weekend handoff — START HERE (2026-06-11)

> **UPDATE 2026-06-12 — roadmap item 1 (stronger compose model) SHIPPED + ACCEPTED.**
> The pipeline's one-shot compose now routes to an optional `compose` role
> (config.yaml ships it on Haiku 4.5; delete the role to restore the certified
> full-local posture). Acceptance re-runs vs the certified baseline:
>
> | Question | Score (was) | Finish (was) | Spend (was) | Haiku share |
> |---|---|---|---|---|
> | sci-aspirin | **8.2** (7.8) | conclusive (time) | $1.13 ($0.35) | $0.26, 6 calls |
> | gen-evbattery | **8.0** (6.6) | conclusive (max_cycles) | $0.95 ($0.77) | $0.26, 5 calls |
>
> Two-question mean **8.1 vs 7.2** (bar: ≥7.7) — and BOTH runs ended
> `conclusive` through the final-evaluator gate, a first. The compose model
> itself costs ~$0.26/question (bar: ≤ +$0.30); the rest of the spend growth
> is Opus bookends doing MORE work because runs now converge instead of dying
> at breakers. Scores: `evals/results/compose-haiku-{sci,gen}/scores.json`.
> Ablation flags: `--compose-model/--compose-endpoint` on run_evals.py.
> Next up: roadmap item 2 (deeper question trees).

> **UPDATE 2026-06-15 — roadmap item 2 (deeper question trees) — machinery shipped + a real bug fixed.**
> Built: question `depth` field, tree bounds (`question_tree.max_depth/max_questions`),
> `--comprehensive` switch (promotes a deep cycles/wall/budget/seed bundle), richer
> 12-facet seeding. THE bigger win came from running it for real: the local
> evaluator was **re-emitting existing questions as "new" every cycle** (a
> comprehensive run had 35 questions = 13 real facets + 22 near-verbatim
> duplicates), which blocked convergence. Fixed with engine-side dedup
> (`common.duplicate_question_id`, difflib ≥0.90). Re-validation: **17 distinct
> questions, 0 duplicates** (was 13/35), 4 dup-drops logged. 155 tests.
> CAVEAT: hierarchical *depth* stays flat — local workers don't fragment and the
> local evaluator won't set `parent_id` even when instructed; guaranteed depth
> needs the Opus initializer to seed a 2-level tree (open decision). Comprehensive
> runs still need real wall-clock (hours) to reach `conclusive` — short test caps
> finish on `time`. Commits: 76ff2d9, cf812e4, 833c165.

Pick up in VSCode: `git pull` on branch `claude/tender-keller-gdae8u`, then read
this file. Everything below is current as of the certification run that
finished 2026-06-11 10:18.

## TL;DR — the engine is CERTIFIED and viable

A hybrid local research engine runs on this PC: local models do all the
volume work ($0), cloud Opus touches only the bookends. **Certification:
mean 7.2/10 across the quick subset, $1.11 for the batch** — within the
handoff's 1.5-of-baseline bar. The scientific profile (the Clinical Index use
case) is the strongest at **7.8 with source_quality 8**.

Two finished reports to read right now (tracked in the repo):
- `docs/examples/aspirin-scientific-7.8.md` — scientific profile, 106 reads,
  55 sources, every claim cited. The judge called it "genuinely solid,
  trustworthy... appropriately calibrated... avoids overreach."
- `docs/examples/ev-battery-general-8.0.md` — general profile, the 8.0 run.

## Certification results (run 2026-06-11)

| Question | Profile | Score | Finish | Spend | Notes |
|---|---|---|---|---|---|
| sci-aspirin | scientific | **7.8** | time | $0.35 | source_quality 8 — scraper+PMC routing got primary sources |
| gen-evbattery | general | 6.6 | max_cycles | $0.77 | blog-heavy topic; source_quality 5 is the open-web ceiling here |
| vis-supplement-trust | visual | — | (boundary) | $0 | visual needs the AGENTIC worker (in-loop capture); see Known Boundaries |
| **batch** | | **7.2** | | **$1.11** | CERTIFIED |

Per-question reports live under `runs/<run-id>/REPORT.md` (gitignored — the two
best are copied into `docs/examples/`). Raw scores:
`evals/results/cert-final/scores.json`.

## What's running right now

**Nothing.** The certification finished. No background tests are active. The PC
can sit idle or you can kick off runs from VSCode (commands below).

## How to run the engine yourself (VSCode terminal)

Prereqs that must be up (they survive reboot via auto-start / restart policy,
but verify): Ollama serving (`ollama ps`), Docker + SearXNG
(`docker --context desktop-linux ps` shows `searxng`). If SearXNG is down:
`docker --context desktop-linux start searxng`.

```powershell
# activate + a single research run (scientific profile is the strongest)
$env:PYTHONUTF8 = '1'
.venv\Scripts\python.exe driver.py `
  "your research question here" `
  --profile scientific --max-wall-hours 2 --max-budget-usd 5 `
  --json-summary runs\my-run.json
# report lands at runs\<run-id>\REPORT.md
```

```powershell
# the community lens (human-perspective section) — NEW this session
.venv\Scripts\python.exe driver.py "your question" --profile general --lens community ...
```

```powershell
# re-run the certification any time
powershell -File runs\certify.ps1   # writes runs\certify-done.txt + per-question reports
```

Resume a killed run losslessly: `... driver.py --resume <run-id>`.

## What was built this session (all committed, all reviewed-ready)

Beyond the original handoff scope:
- **Pipeline-worker mode** — local models do single-shot query-gen + compose;
  the engine runs the loop. This is what made local workers viable (the
  agentic-local path is dead on 16GB; see `docs/LOCAL_SETUP_REPORT.md`).
- **Two-tier evaluation** — local evaluator every cycle ($0), Opus final gate
  only to END a run, capped at `max_final_evaluations`. The cost lever.
- **Scraper** (Scrapling stealth) — browser-rendered retry on 403/JS-only
  pages. `reader.stealth_fallback`.
- **Reranker** (FlashRank, CPU/ONNX — zero GPU contention) — reads the
  most on-topic pages first. `worker_pipeline.rerank`.
- **Community lens** — forum/Reddit perspective on a quarantined track + its
  own report section. `--lens community`. (`docs/COMMUNITY_LENS_SPEC.md`)
- **Legal** scaffolded as a future domain profile.
- **Hard-block convergence** — unanswerable seed facets now close so runs
  converge instead of stalling.
- **Wall-timeouts + provisional ledger** — overnight runs can't hang or hide
  spend.
- Windows lock fix, `-32k` Modelfile variants, 143 tests green.

## Known boundaries (not bugs — design facts)

- **Visual profile needs the agentic (cloud) worker.** Page-capture requires
  in-loop screenshot decisions the single-shot pipeline worker doesn't make.
  Run visual with `worker_pipeline.enabled: false` and a cloud worker model —
  a deliberately different (higher) cost tier. The pipeline/local posture is
  for text research.
- **General-profile quality is capped by open-web source quality.** Blog-heavy
  topics (EV batteries) top out ~6.6 because the good sources are vendor blogs.
  Scientific tops out higher (7.8) because PMC/journals are primary. This is
  honest grading, not a defect.
- **The 9B compose model is the synthesis-quality ceiling.** See the roadmap
  for the cheapest lever to push past 8 (route just compose to a stronger
  model).

## Next steps — APPROVED roadmap (specs ready for the cloud session)

You approved three directions for comprehensive ("8-hour+") research. Full
spec: **`docs/COMPREHENSIVE_RESEARCH_SPEC.md`**. In build order:

1. **Stronger compose model** (cheapest quality jump) — route only the
   one-shot compose step to Haiku or a 27B; readers stay local/free. Targets
   the 8→9 synthesis-calibration ceiling.
2. **Deeper question trees** — richer initializer + multi-level decomposition;
   raise `max_cycles`. Breadth.
3. **Verification wave** — every load-bearing claim handed to an independent
   worker that tries to REFUTE it. The real trust differentiator vs
   Gemini/Claude research.
4. **Wave orchestration** — breadth → depth → verify → synthesize, as
   question-selection policies over the existing loop. Enables 8-hour runs
   that buy depth, not spinning.

Hardware lever (conditional on the pipeline proving useful — it now has):
**second GPU** turns serial reads into 4–8-way fan-out — the biggest
scale unlock. Not required to start; items 1–4 are software.

## Where to resume

- Branch: `claude/tender-keller-gdae8u` (everything pushed).
- The cloud session's task: implement `docs/COMPREHENSIVE_RESEARCH_SPEC.md`,
  review commits since `dc9508c`.
- This session's full forensic record: `docs/LOCAL_SETUP_REPORT.md`.
