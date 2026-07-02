# Runbook — local/hybrid setup, validation run, and the model bake-off

Everything here runs on **your machine** (normal internet egress + GPU/RAM).
The build container can't do these: it 403-blocks model-weight hosts and the
open web, and it pins spawned-session auth to a host broker (see
`docs/SDK_NOTES.md` → "Host-broker auth override"). So this is the
machine-side companion to what's already verified in-repo.

> Run everything from the repo root with the project venv:
> `python -m venv .venv && .venv/bin/pip install -r requirements.txt`
> and a `.env` containing `ANTHROPIC_API_KEY=...` (and `OLLAMA_AUTH=ollama`).

---

## 1. Ollama (local reader / worker backend)

Needs **Ollama ≥ 0.14** — that's the version that serves the Anthropic
Messages API at `/v1/messages`, which is what the engine's `local` endpoint
targets.

```bash
# install per https://ollama.com, then:
ollama --version            # must be >= 0.14

# CRITICAL: raise the context window. Ollama's default (~4–8K) silently
# truncates the page text the engine hands readers — exactly the quiet
# degradation this project refuses. Reader pages are budgeted to 24k chars
# (~8–10k tokens) plus the prompt, so give it real headroom:
export OLLAMA_CONTEXT_LENGTH=32768
export OLLAMA_HOST=0.0.0.0:11434      # serve the LAN so the driver can run anywhere
ollama serve
```

### Model pulls by machine

| machine | reader candidates | worker candidates |
|---|---|---|
| PC (5070 Ti 16GB VRAM, 64GB DDR4/DDR5) | `qwen3:14b`, `gpt-oss:20b` | `gpt-oss:20b`, `qwen3:14b` |
| stretched onto DDR5 (partial CPU offload) | `qwen3:30b-a3b`, `gpt-oss:120b` (MoE — only the active experts hit RAM) | same |
| MacBook Pro M5 24GB | `qwen3:14b` | `qwen3:14b` |

```bash
ollama pull gpt-oss:20b
ollama pull qwen3:14b
# MoE models stretch onto system RAM gracefully; dense >20B on DDR4 will be slow.
```

Point the engine at it in `config.yaml`:

```yaml
endpoints:
  local:
    base_url: http://<pc-ip>:11434   # or localhost if same machine
    auth_env: OLLAMA_AUTH
roles:
  reader_subagent: {endpoint: local, model: gpt-oss:20b, max_turns: 12}
  # later, to test a local worker:
  # worker:        {endpoint: local, model: gpt-oss:20b, max_turns: 50}
```

---

## 2. Pre-flight: verify the endpoint AND auth isolation

**Before any real hybrid run.** This validates JSON compliance, that the
model is usable for the reader role, `usd:0` ledger attribution, and — through
a recording proxy — that no ambient Claude Code credential leaks to the local
endpoint:

```bash
.venv/bin/python scripts/check_local_backend.py --model gpt-oss:20b
# exit 0 + "LOCAL BACKEND CHECK PASSED" => safe to route readers here.
# If it reports a non-placeholder bearer reaching the endpoint, STOP:
# a real credential is leaking — fix before running hybrid.
```

If `[2/4]` fails with a JSON-parse error, that model is unsuitable for the
reader role (§1) — try another. If it passes, you're cleared.

---

## 3. SearXNG (web search for local-routed workers)

Only needed if you route the **worker** (not just readers) to a local/
non-first-party endpoint — Anthropic-hosted WebSearch doesn't exist there, and
the engine refuses to start a local worker without this configured.

```bash
docker run -d --name searxng -p 8888:8080 \
  -e "SEARXNG_BASE_URL=http://localhost:8888/" searxng/searxng
# enable the JSON output format in its settings.yml (formats: [html, json])
```

```yaml
# config.yaml
search:
  searxng_base_url: http://localhost:8888
```

---

## 4. Playwright (visual profile)

```bash
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
```

Then a visual run captures real pages into `runs/<id>/captures/` and the
vision reader (cloud Haiku) analyzes them. Verify ≥5 captures land and the
visual evaluator stops failing-for-lack-of-captures.

---

## 5. The validation run (the real proof)

The in-container smokes all ran in degraded mode (`require_reads: false`,
snippet-only). This is the first run that exercises real depth: forced
full-page reads, hybrid cost, multi-hour fail-and-deepen.

```bash
# hybrid: readers local ($0), judgment on cloud Opus, reads REQUIRED
.venv/bin/python driver.py \
  "Does daily low-dose aspirin reduce first cardiovascular events in healthy adults over 60, and what do current guidelines recommend?" \
  --profile scientific --max-wall-hours 2 --max-budget-usd 15 \
  --json-summary runs/aspirin-summary.json
```

Watch for, in `PROGRESS.md` / the ledger:
- worker cycles showing **non-zero reads** (the read-gate is satisfied by real
  fetches, not snippets);
- reader entries at `endpoint: local`, `usd: 0`;
- the per-cycle cost dropping well below the Phase 2 ~$2/cycle baseline;
- the evaluator fail-and-deepening, then a `conclusive` finish (or a clean
  breaker with a partial report).

Kill it (`Ctrl-C` / `kill -9`) mid-run and `--resume <run-id>` at least once —
resumability is a headline invariant and worth confirming on your hardware.

---

## 6. The model bake-off (answers "which model")

Run the same quick eval subset with the worker (or reader) re-pointed per
candidate; the Opus judge scores each, and you diff the `scores.json` files.
This is the empirical answer to "can a quantized model do Sonnet's job" and
"is a cheaper API equivalent" — not a forum opinion.

```bash
# baseline (Sonnet worker, Haiku readers)
.venv/bin/python evals/run_evals.py --subset quick \
  --max-wall-hours 1 --out evals/results/baseline

# worker -> Haiku (≈3x cheaper, first-party, keeps WebSearch)
.venv/bin/python evals/run_evals.py --subset quick \
  --worker-model claude-haiku-4-5 --out evals/results/worker-haiku

# worker -> local Ollama (free; needs SearXNG from step 3)
.venv/bin/python evals/run_evals.py --subset quick \
  --worker-endpoint local --worker-model gpt-oss:20b \
  --out evals/results/worker-local

# reader -> local (the recommended cost lever, judgment stays cloud)
.venv/bin/python evals/run_evals.py --subset quick \
  --reader-endpoint local --reader-model gpt-oss:20b \
  --out evals/results/reader-local
```

Each writes `scores.json` with per-criterion judge scores (factual accuracy,
citation accuracy, completeness, source quality, tool efficiency), mean score,
finish reason, spend, and the citation-resolution check. Compare `mean_overall`
and `total_spend_usd` across directories — that table is the decision.

### Testing a cheaper third-party API (DeepSeek/Groq/GLM/…)

Add it as an endpoint **with pricing** so the budget breaker sees real spend
(the §1 `usd:0` rule is for *free* local only):

```yaml
endpoints:
  deepseek:
    base_url: https://api.deepseek.com/anthropic   # an Anthropic-compatible path
    auth_env: DEEPSEEK_API_KEY                      # add to .env
    price_per_mtok: {input: 0.27, output: 1.10}     # that provider's rates
```

```bash
.venv/bin/python evals/run_evals.py --subset quick \
  --worker-endpoint deepseek --worker-model deepseek-chat \
  --out evals/results/worker-deepseek
```

If the provider isn't natively Anthropic-compatible, front it with a LiteLLM
proxy and point `base_url` at that (per CLAUDE.md §1).

---

## 7. Full eval set

Drop `--subset quick` to run all ~20 questions across the four domains. Budget
accordingly (it's ~20 full research runs); use `--max-wall-hours` /
`--max-budget-usd` to bound it. The resulting `scores.json` is the
cross-domain quality baseline to track as the engine evolves.
