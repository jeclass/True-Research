# CLAUDE.md — Marathon Research Engine (build spec)

> **For the Claude Code session reading this:** this is a build specification, not a finished
> codebase. Build it in the phases below, in order. Stop at the end of each phase and run the
> stated smoke test before continuing. Surface tradeoffs out loud; never paper over a failure with
> a silent fallback. When a decision is ambiguous, prefer the simplest thing that satisfies the
> invariants in §3.

## 0. What we are building and why

A **multi-hour autonomous research agent**. Not a 5-minute search-and-summarize. The target is a
system that takes one hard question and investigates it for **2–6 hours unattended**, following
leads, cross-validating sources, adjudicating contradictions, and stopping only when the answer is
**conclusive and every claim is traceable to a source**.

The core insight that drives the whole design:

> **"Multi-hour" is a property of a deterministic driver loop, not of any model or framework.**
> A single LLM session is good for ~5–20 minutes before context degrades. Hours come from chaining
> many short, *amnesiac* sessions against state held on disk. The folder is the memory. The loop is
> the hours. The evaluator is the conclusiveness.

We are building on the **Claude Agent SDK** (Python). Reasons: batteries included (WebSearch,
WebFetch, file tools, bash, automatic context compaction, subagents, session resume/fork, hooks,
MCP client), and it reuses everything from this Claude Code environment 1:1. We are **not** using
LangGraph/LangChain here — that was the right call for adopting an off-the-shelf research app, but
for a from-scratch custom build the SDK is lower-friction. Do not add LangGraph.

### Use cases this must serve (it is general-purpose)
The engine is domain-agnostic. The same loop must handle:
- **Scientific / clinical evidence** research (PubMed, OpenAlex, Semantic Scholar — for The Clinical Index).
- **Conversion psychology for product imagery** and **brand-portrayal analysis** — these are *visual*
  tasks; the engine needs a worker that can capture and *look at* web pages, not just read article text.
- **Business / market / legal / patent** research and open-ended personal research.

What changes per domain is the **tool set** and the **rubric**, not the architecture. Implement these
as swappable "research profiles" (§7), never as forks of the core loop.

## 1. Tech + environment

- **Language:** Python 3.11+
- **Core dep:** `claude-agent-sdk` (Anthropic Agent SDK). Use API-key auth via `ANTHROPIC_API_KEY`.
  **Do not** wire this to a Max/Pro subscription or the `claude -p` subscription path — automated
  agent use requires an API key under the Commercial Terms, and the subscription path is metered and
  not built for unattended loops. (The human keeps Max for interactive Claude Code; the *engine* runs
  on API keys.)
- **Other deps:** `pydantic` (state schemas + validation), `pyyaml`, `tenacity` (retry), `rich` (CLI
  progress), `httpx`. Add search/academic tooling only in Phase 4.
- **Config:** all knobs in `config.yaml`, loaded into a frozen Pydantic `Settings` object. No magic
  numbers in code.
- **Secrets:** `.env` (gitignored). Never commit keys. Provide `.env.example`.

### Model routing (do this — it is the cost lever)
Route by cognitive density, not convenience. Set these as defaults in `config.yaml`:
- **Lead / Initializer / Evaluator / Synthesizer / contradiction adjudication → Opus 4.8**
  (`claude-opus-4-8`). The judgment work.
- **Worker session driver → Sonnet 4.6** (`claude-sonnet-4-6`).
- **Fan-out subagents that read individual sources → Haiku 4.5** (`claude-haiku-4-5-20251001`).
- Turn on **prompt caching** for stable context (system prompts, the source registry, profile rubric).
- A 3-hour run with this routing should land around **$8–20**. Frontier-only would be ~10×. If a run
  is burning faster than that, stop and report — do not silently continue.

### Model backends — cloud, local, hybrid (design for this from Phase 1)

Every session role resolves its model through an endpoint in config — never a hardcoded string:

```yaml
endpoints:
  anthropic:                              # default cloud
    base_url: null                        # SDK default (api.anthropic.com)
    auth_env: ANTHROPIC_API_KEY
  local:
    base_url: http://localhost:11434     # Ollama >= v0.14 serves the Anthropic Messages API natively
    auth_env: OLLAMA_AUTH                 # value "ollama" — required by the protocol but ignored
roles:
  initializer:     {endpoint: anthropic, model: claude-opus-4-8}
  worker:          {endpoint: anthropic, model: claude-sonnet-4-6}
  reader_subagent: {endpoint: anthropic, model: claude-haiku-4-5-20251001}
  evaluator:       {endpoint: anthropic, model: claude-opus-4-8}
  synthesizer:     {endpoint: anthropic, model: claude-opus-4-8}
```

**Mechanism:** Ollama v0.14+ exposes an Anthropic-compatible `/v1/messages` API, so the Agent SDK /
Claude Code can target a local model by setting `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` for the
spawned session. Inject these **per spawned session** in `sessions/base.py` — never set them on the
global process env — so a single cycle can mix backends (hybrid). For LM Studio / vLLM / llama.cpp,
front them with an Anthropic-format translation proxy (LiteLLM or Olla) and point `base_url` at it.

**Recommended local posture = hybrid, not full-local.** Local models (pick strong tool-callers with
≥32K context — e.g. `gpt-oss:20b`, `glm-4.7-flash`, Qwen3-class MoEs) take the high-volume
`reader_subagent` role: zero marginal cost and privacy where quality matters least. Keep evaluator,
adjudication, and synthesis on cloud Opus — judgment is where local models degrade most and where
conclusiveness lives. Full-local is permitted via config but must log a loud warning at run start.

**Local-mode constraints (encode these, don't discover them):**
- `WebSearch` is an Anthropic-hosted tool and does not exist against a local endpoint. Local/hybrid
  profiles must supply search via MCP — SearXNG for fully-local, Tavily/Exa otherwise. Verify
  `WebFetch` behavior against the local endpoint during Session 0 and record it in `docs/SDK_NOTES.md`.
- Tool-calling reliability varies wildly across local models. The typed-error + stall machinery must
  surface "model unsuitable for tool use" after repeated malformed tool calls — never retry forever.
- Ledger entries gain an `endpoint` field. Local sessions log `usd: 0` but still record tokens and
  wall-clock, so every finding is attributable to the brain that produced it.

## 2. Directory layout

```
marathon-research/
├── CLAUDE.md                  # this file
├── config.yaml                # all tunable knobs
├── .env.example
├── README.md
├── driver.py                  # entrypoint: the deterministic loop (NO LLM logic here)
├── src/
│   ├── settings.py            # frozen Pydantic Settings from config.yaml + .env
│   ├── state.py               # Pydantic models for all run-state files + load/save/validate
│   ├── runspace.py            # create/resolve runs/<id>/ dirs, atomic file writes, locks
│   ├── ledger.py              # cost + token accounting from SDK usage; budget circuit breaker
│   ├── sessions/
│   │   ├── base.py            # thin wrapper around the Agent SDK: spawn a fresh session,
│   │   │                      #   enforce max_turns + per-session budget, capture usage,
│   │   │                      #   structured-output parsing, typed errors
│   │   ├── initializer.py     # QUESTION.md -> PLAN.md + open_questions.yaml
│   │   ├── worker.py          # take top open question -> findings/*.md + source updates
│   │   ├── evaluator.py       # FRESH context, default-FAIL rubric -> verdict + new questions
│   │   └── synthesizer.py     # findings -> REPORT.md + citation pass
│   ├── profiles/              # swappable research profiles (tools + rubric per domain)
│   │   ├── base.py            # Profile interface: tools(), rubric(), worker_guidance()
│   │   ├── general.py
│   │   ├── scientific.py      # academic MCP servers + evidence-grading rubric
│   │   └── visual.py          # page-capture tools + visual-analysis rubric
│   └── tools/                 # custom tool / MCP wiring (Phase 4+)
└── runs/                      # one subdir per research run (gitignored)
    └── <run-id>/
        ├── QUESTION.md
        ├── PLAN.md
        ├── open_questions.yaml
        ├── findings/
        │   └── <slug>.md
        ├── sources.json       # the source registry — every source gets a stable ID
        ├── PROGRESS.md        # human-readable session log
        ├── ledger.json        # machine cost/turn log
        ├── verdicts/
        │   └── cycle-<n>.md
        └── REPORT.md          # final output (written by synthesizer)
```

## 3. Invariants (the no-silent-failures contract)

These are non-negotiable. Encode them as assertions/guards, not hopes.

1. **Sessions are amnesiac.** No session receives another session's conversation history. Every
   session's entire input is (a) its system prompt, (b) the relevant files from `runs/<id>/`. State
   lives on disk, never in a long-lived context window.
2. **The evaluator fails by default.** It is a *separate* Opus session with no memory of the worker's
   effort. A run is "done" only when the evaluator explicitly passes AND `open_questions.yaml` has no
   `open` items AND budget/time remain. Absence of evidence = FAIL, not pass.
3. **Every claim is traceable.** Findings record claims with a `source_id` that must exist in
   `sources.json`. The synthesizer refuses to emit a claim whose `source_id` is missing. A claim with
   no source is a bug, surfaced loudly.
4. **Two circuit breakers, always armed.** `max_turns` per session (SDK default is unlimited — set it)
   and a global `max_budget_usd` + `max_wall_clock_hours` checked by the driver before every session.
   Tripping a breaker ends the run cleanly with a partial report, never a crash.
5. **Stall detection.** If two consecutive worker cycles produce no change to `findings/` or
   `open_questions.yaml` (hash the dir), halt and report a stall. Do not loop forever.
6. **Atomic state writes.** Write to a temp file + rename. A crash mid-write must never corrupt state.
7. **Resumable.** `python driver.py --resume <run-id>` reconstructs everything from disk and continues
   from the next cycle. No run state is ever held only in memory.
8. **Tradeoffs surfaced.** When the engine makes a consequential choice (dropped a low-credibility
   source, narrowed scope to fit budget, couldn't access a paywalled source), it logs it to PROGRESS.md
   under a `DECISIONS` heading. Silent narrowing is forbidden.

## 4. State schemas (Pydantic — define in src/state.py)

Keep these tight; validate on every load and save.

- **`open_questions.yaml`** — list of `{id, question, status: open|in_progress|resolved, priority: 1-5,
  parent_id, created_by: initializer|evaluator, resolved_by_finding}`. This file is the loop's fuel:
  workers pull the highest-priority `open` item; the evaluator appends new ones when it finds gaps.
- **`sources.json`** — dict keyed by `source_id` → `{url, title, kind: web|paper|page_capture,
  credibility: 0-100, retrieved_at, notes}`. The registry behind every citation.
- **finding file (`findings/<slug>.md`)** — front-matter `{question_id, source_ids: [...], confidence}`
  then prose. Every factual sentence ties to a source_id in the front matter.
- **`ledger.json`** — append-only list of `{cycle, session_type, model, endpoint, input_tokens,
  output_tokens, cached_tokens, usd, wall_seconds}`.
- **verdict (`verdicts/cycle-<n>.md`)** — `{passed: bool, unmet_criteria: [...], contradictions: [...],
  new_questions: [...], notes}`.

## 5. The driver loop (driver.py — deterministic, no LLM calls of its own)

```python
# pseudocode — implement against the real SDK
def main(question_or_run_id, resume=False):
    settings = load_settings()                       # frozen, from config.yaml + .env
    run = Runspace.resume(run_id) if resume else Runspace.create(question)
    ledger = Ledger(run)

    if not resume:
        run_session(Initializer, run, settings)      # QUESTION -> PLAN + open_questions
        ledger.checkpoint()

    cycle = run.last_cycle()
    while True:
        # --- circuit breakers, checked BEFORE every session ---
        if ledger.spend_usd >= settings.max_budget_usd:  return finish(run, reason="budget")
        if run.wall_hours()  >= settings.max_wall_hours:  return finish(run, reason="time")
        if cycle             >= settings.max_cycles:      return finish(run, reason="max_cycles")

        before = run.state_hash()
        run_session(Worker, run, settings)            # investigate top open question
        ledger.checkpoint()

        run_session(Evaluator, run, settings)         # FRESH context, default-FAIL
        verdict = run.latest_verdict()
        ledger.checkpoint()

        if verdict.passed and run.no_open_questions():
            return finish(run, reason="conclusive")   # the ONLY success exit

        if run.state_hash() == before:                # stall guard (invariant 5)
            run.log_decision("STALL: no state delta across a full cycle; halting.")
            return finish(run, reason="stall")

        cycle += 1

def finish(run, reason):
    run.log(f"Run ending: {reason}")
    run_session(Synthesizer, run, settings)           # always write a report, even partial
    print_summary(run, reason)
```

The driver contains **zero** prompt text and **zero** model calls beyond `run_session`. All cognition
is inside the session modules. This separation is the point: the loop is auditable, the cognition is
swappable.

## 6. Session modules (src/sessions/) — the cognition

Each module builds a system prompt, selects tools (from the active profile), spawns ONE fresh Agent
SDK session, and returns parsed structured output. `base.py` enforces `max_turns`, per-session budget,
usage capture, and typed errors (`PlanningError`, `WorkerError`, `EvalError`, `SynthesisError`).

- **Initializer (Opus):** Expand QUESTION.md into a research PLAN and a seed set of prioritized open
  questions. Decompose breadth-vs-depth. Write PLAN.md + open_questions.yaml. No web access needed.
- **Worker (Sonnet driver + Haiku subagents):** Read PLAN, PROGRESS, open_questions. Take the single
  highest-priority `open` question, mark it `in_progress`. Investigate: issue searches, fan out
  **subagents** to read individual sources in parallel (each returns a compressed summary + the
  source's metadata), register every source in sources.json with a credibility score, write a finding
  file with claims tied to source_ids, mark the question `resolved` (or spawn child questions if it
  fragments). Append a PROGRESS entry. Touch ONE primary question per session so cycles stay bounded.
- **Evaluator (Opus, FRESH context):** This is the quality gate. Given only the files on disk and the
  active profile's rubric, grade the body of findings. **Start from FAIL.** Check: are all open
  questions resolved? Does every claim trace to a real source_id? Are there contradictions between
  findings? Is source quality adequate for the domain? Output a verdict; when it finds gaps or
  contradictions, append new prioritized open questions (this is how depth accrues). The evaluator
  may pass only when it can defend conclusiveness.
- **Synthesizer (Opus):** Compose REPORT.md from findings. Then a dedicated **citation pass**: every
  claim in the report must carry its source_id and resolve against sources.json; unresolved → flag,
  don't emit. Include a "limitations & decisions" section drawn from the PROGRESS DECISIONS log.

## 7. Research profiles (src/profiles/) — how it serves "everything"

A `Profile` supplies three things to the sessions: `tools()` (which tools/MCP servers workers get),
`rubric()` (what the evaluator demands), and `worker_guidance()` (domain instructions injected into the
worker prompt). Selected via `--profile` or auto-detected by the initializer.

- **general** — Exa/Tavily web search + WebFetch; rubric weights breadth, source diversity, recency.
- **scientific** — adds academic MCP servers (PubMed/OpenAlex/Semantic Scholar/arXiv via a
  paper-search MCP); rubric demands evidence grading (study type, sample size, peer-review status) and
  penalizes non-primary sources. This is the profile The Clinical Index work uses.
- **visual** — adds a **page-capture tool** (screenshot via Playwright/Firecrawl) so workers can pull
  hero images, listings, and landing pages, then **Claude vision** analyzes layout, claim density,
  badge/social-proof placement, lifestyle-vs-white-background ratios across the top N competitors;
  rubric demands coverage of N examples and visual-pattern evidence, not just article text *about*
  imagery. This is what makes the Amazon-image-psychology and brand-portrayal use cases real.

Adding a domain = adding one Profile. The loop, state, and invariants never change.

## 8. Build phases (do these in order; smoke-test each)

**Phase 1 — Skeleton + the loop (no real cognition).**
Build settings, state schemas, runspace, ledger, the driver loop, and a **stub** worker/evaluator that
just read/write files and return canned output. Goal: prove the loop, circuit breakers, stall
detection, atomic writes, and `--resume` all work with zero LLM cost.
*Smoke test:* run with tiny caps; confirm it cycles, trips a budget breaker cleanly, resumes from disk,
and halts on a forced stall.

**Phase 2 — Real sessions, built-in tools only.**
Implement Initializer, Worker, Evaluator, Synthesizer against the Agent SDK using only built-in
WebSearch/WebFetch + file tools. Wire model routing (§1). Implement the source registry + claim→source
traceability + the default-FAIL evaluator.
*Smoke test:* one real run on a medium question with `max_wall_hours: 0.5`. Watch PROGRESS.md and
verdicts/ populate. Confirm the evaluator actually fails-and-reopens at least once before passing, and
that REPORT.md claims all resolve to sources.json.

**Phase 3 — Subagent fan-out + caching + the judgment layer.**
Add Haiku subagents for parallel source reading inside the worker. Turn on prompt caching for stable
context. Add the contradiction-adjudication step in the evaluator. Tighten stopping criteria.
*Smoke test:* a 1–2 hour run; verify cost lands in the routed range and the ledger reconciles; verify a
deliberately contradictory pair of sources gets flagged and adjudicated.

**Phase 4 — Profiles + connectors + local backends.**
Implement the Profile interface and the three profiles. Wire the academic MCP server (scientific) and
the page-capture + vision path (visual). Wire the `local` endpoint and hybrid role routing (§1),
including the MCP search fallback for local mode. Optionally add Exa/Tavily for better web retrieval,
and add Gemini Deep Research / OpenAI deep-research as *callable worker tools* for turnkey sub-reports.
*Smoke test:* run the same question under `general` then `scientific`; run a `visual` question that
captures and analyzes ≥5 competitor pages; rerun the smoke question with `reader_subagent` routed to a
local Ollama model and confirm the ledger attributes those sessions to `endpoint: local` at `usd: 0`.

**Phase 5 — Hardening.**
Typed exceptions everywhere, retry-with-backoff on transient API/search failures (tenacity), a
~20-question eval set across the four domains scored by an LLM-judge rubric (factual accuracy, citation
accuracy, completeness, source quality, tool efficiency), and LangSmith-style tracing if desired. Add
an optional outer scheduler hook so the engine can be triggered by the existing orchestrator/24-7 swarm.
*Smoke test:* the eval set runs end-to-end and produces comparable scores across runs.

## 9. Explicitly out of scope (do not add unless asked)
Temporal, Ray, Celery, RabbitMQ, Kubernetes, a web UI, a vector DB. A checkpointer-on-disk + cron +
tracing is the right-sized envelope for a single operator. Add heavy infra only when something
concretely breaks at scale — and say so when you propose it.

## 10. Definition of done (MVP)
`python driver.py "<a hard question>" --profile scientific` runs unattended for up to the configured
budget/time, produces a REPORT.md where **every claim resolves to a source**, fails-and-deepens via the
evaluator until conclusive or a breaker trips, logs all costs and decisions, and can be killed and
`--resume`d without losing a cycle. The same command with `--profile visual` analyzes real captured
pages, not articles about them.
