# Pipeline-worker mode — spec for the cloud session

Operator-approved engine feature (2026-06-10). Goal: make the worker role
viable on the operator's local models **today**, on the existing 16GB card,
by removing the open-loop agentic span that small models empirically cannot
hold. Operator's hard constraint: **$1–2 per multi-hour run, locals must
work** — Sonnet/Opus/Haiku-per-cycle routing is not acceptable as the
end state.

## Why (one day of evidence, all on the operator's machine)

Single-shot local sessions are essentially perfect; multi-turn agentic local
sessions are dice-rolls:

| Pattern | Local model | Result |
|---|---|---|
| Reader (single-shot JSON, no tools) | gpt-oss:20b, qwen3.5:9b/4b | **flawless all day** — 34/34, 12/12, 5/5 reads across every run |
| Preflight (single-shot prompted-JSON) | all four models | PASS |
| Worker (20–50-turn tool loop) | qwen3.5:9b (Ollama 0.30.7, 32k ctx) | 3 attempts, 3 distinct failures: `signature` transport (fixed by 0.30.7) → citation-id typo (`src-gtab-u-k-pr-2024-degrat`, evals/results/qwen-worker-0307-32k) → empty final output (…-r2) |
| Worker (agentic) | gpt-oss:20b | 0/6 across two legs: cite-without-read ×3, id collision, unparseable JSON ×2 (evals/results/worker-gptoss*) |

Four specific barriers were fixed during the day (transport via Ollama
0.30.7; 4k-context truncation via baked `-32k` model variants; read-gate
disclosure in the worker prompt; exact-id rule) and the agentic loop still
fails — each run finds a new failure mode. It is compounding per-turn
flakiness, not a bug. External research (operator's June 2026 model report)
agrees: agentic-worker-capable local models start at Qwen3.6-27B-class,
which needs 32GB.

## Design

Opt-in worker mode; the agentic path stays the default.

```yaml
# config.yaml
worker_pipeline:
  enabled: false          # true => worker.run() takes the pipeline path
  queries_per_question: 4 # one-shot query-gen output cap
  urls_per_query: 4       # rule-based selection cap, post-dedupe
  max_reads: 14           # total reader fan-out budget per question
```

Flow inside `worker.run()` (everything reuses existing machinery):

1. **Query-gen (one-shot local session, no tools).** Input: assigned
   question + plan + registry digest. Output schema:
   `{queries: [str], notes: str}`. Reuses `run_role_session` with
   `output_model`, `tools=[]` — the exact shape readers/preflight use.
2. **Search (engine code, no LLM).** Execute each query against SearXNG
   (`search.searxng_base_url`, client already exists for the local-worker
   search MCP). Collect results.
3. **URL selection (engine code, no LLM).** Top `urls_per_query` per query
   after: dedupe by `common.normalize_url`, skip already-registered URLs,
   cap per-domain (2), apply profile URL preferences (scientific: prefer
   pmc.ncbi.nlm.nih.gov / europepmc.org — same list as the 7a93caa prompt
   guidance, now enforced in code).
4. **Reader fan-out (existing).** `reader.read_source` on every selected
   URL up to `max_reads`, parallel as today. Engine collects
   useful-read outputs.
5. **Engine builds the sources array itself** from reader metadata
   (id slugified from title+year, url = the URL actually read, title/kind/
   credibility/notes copied verbatim). **The model never types a URL or
   invents an id** — invariant 3's failure classes (cite-without-read,
   id typos, collisions) become structurally impossible.
6. **Compose (one-shot local session, no tools).** Input: question + the
   summaries + a menu of the valid `[src-...]` ids. Output: existing
   `WorkerOutput` schema minus `sources` (engine-supplied): outcome,
   finding.body_markdown citing ONLY menu ids, confidence,
   child_questions/blocked_reason, progress_note.
7. **Apply (existing).** Same `_apply_resolved` / `_apply_fragmented` /
   `_apply_blocked` gates, unchanged. A cited id outside the engine-built
   registry still fails loudly — the gate stays armed.

Ledger: steps 1 and 6 are two local sessions (usd 0); reads ledger as today.
PROGRESS note should record mode=pipeline + query list (DECISIONS if the
read budget truncated candidates).

## Constraints

- Driver loop, invariants (§3), state schemas: untouched.
- Mode must compose with profiles (worker_guidance text feeds the compose
  prompt; profile URL preferences feed step 3).
- Evaluator/synthesizer unchanged. Default config keeps `enabled: false`.
- Tests: unit-test steps 3 and 5 (pure functions); a stub-backend test for
  the pipeline branch; suite stays green.

## Acceptance (run on the operator's machine — local session will validate)

1. `scripts/smoke_test.ps1` equivalent with
   `--worker-endpoint local --worker-model qwen3.5-9b-32k` AND
   `qwen3.5-4b-32k` on `gen-evbattery`: judge mean ≥ 7.0, zero invariant-3
   errors, 3 consecutive passes per model (flakiness is the enemy — one
   pass proves nothing, see the retest trilogy).
2. Budget-config certification: `--subset quick` with
   `runs/config-budget.yaml` (local pipeline worker + readers, Haiku
   evaluator, Opus init/synth): `mean_overall` within 1.5 of baseline 8.0,
   total leg spend ≤ $1.50.
3. The aspirin question completes ≥3 cycles without invariant-3 halts
   (post-7a93caa Sonnet evidence: runs/bakeoff-baseline-postfix-sci.log).

## Companion work items (same priority order as LOCAL_SETUP_REPORT.md)

1. **[CRITICAL] Session wall-timeout** (`asyncio.wait_for` in
   sessions/base.py): the Claude CLI subprocess died twice today
   (0xC0000409 under system memory pressure) and the engine hung forever
   awaiting the dead transport. Root cause of the crashes themselves was
   orphaned llama-server processes exhausting Windows commit charge —
   but the engine must fail loudly on a dead session regardless.
2. Ledger blind spot: sessions dying mid-flight bill the API but never
   reach the ledger.
3. `--evaluator-model/--evaluator-endpoint` flags for run_evals.py.
4. Engine-level OA-mirror fallback in read_source (step-3 selection rules
   above partially subsume this for pipeline mode; agentic mode still
   benefits).
