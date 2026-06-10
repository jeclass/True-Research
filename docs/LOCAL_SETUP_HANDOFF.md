# Local-backend setup — handoff for a local Claude Code session

You are a Claude Code session running on the operator's PC (RTX 5070 Ti 16GB
VRAM, 64GB system RAM). Your job is to stand up the LOCAL model backend for
the Marathon Research Engine in this repo, validate it with the engine's own
check tools, and run the reader/worker model bake-off. Everything you need is
already built — **this is a configuration-and-verification task, not a
development task.**

## Ground rules

1. **Do not modify engine code** (`src/`, `driver.py`, `evals/*.py`,
   `tests/`). Your surface is: `config.yaml`, `.env`, system services
   (Ollama, SearXNG, Playwright), and running the provided scripts.
2. **No silent fallbacks.** If a step fails, report the error and stop that
   track. The engine's own checks are the acceptance gates — do not work
   around a failing gate.
3. **Verify, don't assume model tags.** The operator's candidates:
   **Qwen 3.5 4B** as the small/quick READER model, and **Gemma 4 12B** +
   `gpt-oss:20b` as WORKER candidates (also bake them off as readers for
   comparison). Reader and worker co-reside on the one 16GB card — a 4B
   reader (~2.5-3GB q4) plus a 12-20B worker is the intended pairing.
   These model families are newer than the docs in this repo — resolve the
   exact Ollama registry tags yourself (`ollama search qwen3.5`,
   `ollama search gemma4`, or https://ollama.com/library) and prefer
   instruct-tuned q4_K_M-class quants. Record the exact tags you used.
   Expectation to carry into the bake-off: 4B in the WORKER role will likely
   fail the JSON/orchestration gates — run the leg anyway and record the
   result; the reader role is where 4B is expected to shine.
4. Read `docs/RUNBOOK.md` first — it is the human-oriented version of this
   plan with extra context. `docs/SDK_NOTES.md` → "Host-broker auth override"
   explains why step 3's auth check exists.

## Step 0 — repo + engine sanity

```bash
git pull                                   # branch: claude/tender-keller-gdae8u
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# .env must contain ANTHROPIC_API_KEY=... and OLLAMA_AUTH=ollama
.venv/bin/python -m pytest tests/ -q       # expect: 86 passed
```

Gate: tests green before touching anything else.

## Step 1 — Ollama service (sized for two models on one 16GB card)

Require **Ollama ≥ 0.14** (`ollama --version`) — earlier versions don't serve
the Anthropic `/v1/messages` API the engine targets.

Configure the service environment (systemd override or shell env) — each line
matters:

```bash
OLLAMA_CONTEXT_LENGTH=32768   # engine readers get ~24k chars of page text;
                              # Ollama's small default silently truncates it
OLLAMA_MAX_LOADED_MODELS=2    # reader + worker models stay resident together
OLLAMA_NUM_PARALLEL=3         # engine readers fan out in parallel
OLLAMA_HOST=0.0.0.0:11434     # only if the driver runs on another machine
OLLAMA_KV_CACHE_TYPE=q8_0     # halves KV memory; needed for 2 models + 32k ctx
```

VRAM budget on 16GB with a 4B reader resident (~2.5-3GB q4 + KV):
- + Gemma 4 12B worker (~7-8GB q4): comfortable; `OLLAMA_NUM_PARALLEL=4` is
  affordable for faster reader fan-out.
- + gpt-oss:20b worker (~13GB MoE): tight — keep `OLLAMA_NUM_PARALLEL=2-3`
  and q8 KV; if `ollama ps` shows CPU/GPU split, drop parallelism first,
  then `OLLAMA_MAX_LOADED_MODELS=1` (eviction between reader/worker calls
  costs seconds per swap but works).

Pull the candidates (exact tags per your step-0 verification):

```bash
ollama pull <qwen3.5-4b-instruct-tag>      # the reader model
ollama pull <gemma4-12b-instruct-tag>      # worker candidate
ollama pull gpt-oss:20b                    # worker candidate / known-good baseline
```

## Step 2 — per-model pre-flight (the acceptance gate)

For EACH pulled model:

```bash
.venv/bin/python scripts/check_local_backend.py --model <tag>
```

This validates, against the engine's exact session plumbing: endpoint
liveness, prompted-JSON compliance (the engine's structured path on local
endpoints), **wire-level auth isolation** (a recording proxy fails the check
if any real `sk-ant-*` credential reaches the local endpoint — this machine
runs Claude Code, which is exactly the leak scenario the check exists for),
and `endpoint: local, usd: 0` ledger attribution.

Gate per model: exit 0. A model that fails the JSON check is **unsuitable for
the reader role** (CLAUDE.md §1) — record it as failed, do not prompt-hack
around it.

## Step 3 — config for hybrid (readers local first)

In `config.yaml`, route readers to the best gate-passing model:

```yaml
roles:
  reader_subagent: {endpoint: local, model: <best-tag>, max_turns: 12}
```

Leave `require_reads: true` (this machine has real egress — the read-gate is
the depth contract). Worker stays on Sonnet for this step.

Validation run (watch for: non-zero reads per worker cycle, reader ledger
entries at `endpoint: local` / `usd: 0`, per-cycle cost well under ~$2):

```bash
.venv/bin/python driver.py \
  "Does daily low-dose aspirin reduce first cardiovascular events in healthy adults over 60, and what do current guidelines recommend?" \
  --profile scientific --max-wall-hours 2 --max-budget-usd 15 \
  --json-summary runs/validation-summary.json
```

Also kill it mid-run once (`kill -9`) and `--resume <run-id>` — resumability
on this hardware is part of the acceptance.

## Step 4 — local worker prerequisites (only for the worker bake-off legs)

A worker routed to `local` loses Anthropic-hosted WebSearch; the engine will
refuse to start without the SearXNG fallback:

```bash
docker run -d --name searxng -p 8888:8080 \
  -e "SEARXNG_BASE_URL=http://localhost:8888/" searxng/searxng
# in its settings.yml enable JSON: search.formats: [html, json], then restart
```

```yaml
# config.yaml
search:
  searxng_base_url: http://localhost:8888
```

Optional (visual profile): `.venv/bin/playwright install chromium`.

## Step 5 — the bake-off (the actual deliverable)

Same quick eval subset per candidate; the cloud Opus judge referees; one
output dir per leg:

```bash
B=.venv/bin/python
$B evals/run_evals.py --subset quick --max-wall-hours 1 --out evals/results/baseline
$B evals/run_evals.py --subset quick --reader-endpoint local --reader-model <qwen3.5-4b> --out evals/results/reader-qwen35-4b
$B evals/run_evals.py --subset quick --reader-endpoint local --reader-model <gemma4-12b>  --out evals/results/reader-gemma4
$B evals/run_evals.py --subset quick --reader-endpoint local --reader-model gpt-oss:20b   --out evals/results/reader-gptoss
# worker legs (needs step 4; reader pinned to the step-3 winner):
$B evals/run_evals.py --subset quick --worker-model claude-haiku-4-5 --out evals/results/worker-haiku
$B evals/run_evals.py --subset quick --worker-endpoint local --worker-model <gemma4-12b> --out evals/results/worker-gemma4
$B evals/run_evals.py --subset quick --worker-endpoint local --worker-model gpt-oss:20b  --out evals/results/worker-gptoss
# expected-to-fail leg, run it anyway and record the outcome:
$B evals/run_evals.py --subset quick --worker-endpoint local --worker-model <qwen3.5-4b> --out evals/results/worker-qwen35-4b
```

Expect worker-local legs to be slower and to FAIL more evaluator cycles —
that is signal, not a bug. If a local worker repeatedly dies on prompted-JSON
validation, the engine will say so loudly; record it as the result.

## Step 6 — report back

Produce a short summary for the operator containing, per leg:
`mean_overall`, per-criterion judge scores, `total_spend_usd`, wall time,
finish reasons, reader-failure counts (from PROGRESS.md), and the exact model
tags + Ollama env settings used. Attach the `evals/results/*/scores.json`
files and the step-3 validation `runs/<id>/REPORT.md`. Commit nothing except
(optionally) `config.yaml` changes the operator approves — results dirs and
runs/ stay untracked.

## Known constraints you inherit (do not re-litigate)

- Judgment roles (evaluator/synthesizer/judge) stay on cloud Opus; vision
  reads stay on cloud Haiku. Full-local triggers a deliberate loud warning.
- A paid third-party endpoint needs `price_per_mtok` in its endpoint config
  or the budget breaker is blind (see RUNBOOK §6).
- `usd: 0` for local entries is by design (§1); tokens and wall time are
  still recorded and are the comparison currency for local legs.
