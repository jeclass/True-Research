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

## Repo map

- `driver.py` — the deterministic loop; zero prompts, zero model calls
- `src/sessions/` — the cognition: one module per session role + SDK wrapper
- `src/{settings,state,runspace,ledger}.py` — config, schemas, atomic run
  state, cost accounting
- `docs/SDK_NOTES.md` — verified Agent SDK facts this build relies on
- `docs/DECISIONS.md` — one line per non-obvious choice
- `tests/` — pytest suite (`.venv/bin/python -m pytest tests/ -q`)
