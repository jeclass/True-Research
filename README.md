# Marathon Research Engine

A multi-hour autonomous research agent: one hard question in, a fully
source-traceable report out. Hours of unattended investigation come from a
deterministic driver loop chaining many short, amnesiac Claude Agent SDK
sessions against state held on disk — the folder is the memory, the loop is
the hours, the evaluator is the conclusiveness. Full build spec: `CLAUDE.md`.

## Quick start

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # add your ANTHROPIC_API_KEY
.venv/bin/python driver.py "your hard research question" --profile general
```

Useful flags: `--resume <run-id>`, `--max-cycles N`, `--max-budget-usd X`,
`--max-wall-hours H`, `--config path` (all defaults in `config.yaml`).

## How a run works

1. **Initializer** (Opus) decomposes the question into a plan + prioritized
   open questions.
2. Each cycle: a fresh **worker** (Sonnet) investigates the top open question
   via web search and registers every source; a fresh **evaluator** (Opus,
   default-FAIL) grades the whole state and opens new questions where it finds
   gaps or contradictions.
3. The loop exits only when the evaluator passes AND no questions remain open —
   or a circuit breaker (budget / wall-clock / cycles) or the stall guard trips.
4. The **synthesizer** (Opus) always writes `REPORT.md` — partial if the run
   ended early — with every claim citing a `[src-...]` id that must resolve
   against `sources.json`.

Every run lives in `runs/<id>/` (gitignored): question, plan,
`open_questions.yaml`, `findings/`, `sources.json`, `verdicts/`, `PROGRESS.md`
(including a DECISIONS log), `ledger.json` (cost per session per endpoint),
and `REPORT.md`. Runs survive `kill -9` and continue with `--resume`.

## Profiles

`--profile general|scientific|visual` (CLAUDE.md §7) swaps the worker's tool
set and the evaluator's rubric, never the loop:

- **general** — web search + reader fan-out; rubric demands breadth, source
  diversity, recency.
- **scientific** — adds PubMed/OpenAlex/arXiv search tools; rubric demands
  evidence tiers, primary sources, n/effect-size/CI on load-bearing claims.
- **visual** — adds `capture_page` (Playwright screenshot + Claude-vision
  analysis); rubric refuses imagery conclusions not grounded in ≥5 captured
  pages (`kind=page_capture`). Needs `pip install playwright && playwright
  install chromium`.

## Hybrid / local backends

Point any role at the `local` endpoint in `config.yaml` (Ollama ≥ 0.14 serves
the Anthropic API natively). Recommended posture: readers local, judgment
(evaluator/synthesizer) on cloud Opus. Local sessions ledger `usd: 0` with
real token counts. Workers routed local need `search.searxng_base_url`
(WebSearch is Anthropic-hosted). Full-local works but warns loudly.

**Before the first hybrid run on a machine**, verify the endpoint AND that no
ambient Claude Code credential leaks to it:

```bash
.venv/bin/python scripts/check_local_backend.py --model qwen3:4b-instruct-2507-q4_K_M
```

Do not run hybrid inside broker-managed sandboxes (e.g. Claude Code on the
web) — see docs/SDK_NOTES.md "Host-broker auth override".

## Repo map

- `driver.py` — the deterministic loop; zero prompts, zero model calls
  (`--json-summary <path>` emits a machine-readable summary for orchestrators)
- `src/sessions/` — the cognition: one module per session role + SDK wrapper
- `src/profiles/` — the swappable domain profiles (tools + rubric + guidance)
- `src/tools/` — connectors: academic search, SearXNG, page capture
- `src/{settings,state,runspace,ledger}.py` — config, schemas, atomic run
  state, cost accounting (per-endpoint pricing for paid third-party backends)
- `evals/` — eval set + Opus judge + `run_evals.py` (bake-off model A/B)
- `scripts/check_local_backend.py` — pre-flight for a local/hybrid endpoint
- `docs/RUNBOOK.md` — machine-side setup, validation run, model bake-off
- `docs/LOCAL_SETUP_HANDOFF.md` — executable plan for a local Claude Code
  session to stand up Ollama + run the bake-off
- `docs/SDK_NOTES.md` — verified Agent SDK facts this build relies on
- `docs/DECISIONS.md` — one line per non-obvious choice
- `tests/` — pytest suite, 86 passing (`.venv/bin/python -m pytest tests/ -q`)
