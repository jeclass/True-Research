# Local setup report — 2026-06-10 (operator PC, RTX 5070 Ti)

Step-6 report for `docs/LOCAL_SETUP_HANDOFF.md`, written by the local Claude
Code session. Everything below ran on the operator's PC (Windows 11, RTX 5070
Ti 16GB, 64GB RAM, Ollama 0.24.0, Docker 28.3.2, Python 3.13).

## Executive summary

- The hybrid pipeline **works end-to-end on this machine**: best full run
  scored **8.0/10** (Opus judge) at **$2.31** with all 34 reads on the local
  GPU at $0.
- **Local models cannot yet hold the worker role un-fixed** — but the two
  prompt fixes below repaired the dominant failure mode, and post-fix the
  formerly-fatal scientific question ran 3 clean cycles. gpt-oss:20b worker
  rescue is being verified now.
- **Two new engine reliability bugs found** (CLI-transport crash → permanent
  hang; unledgered mid-flight spend). These are now the top blockers for
  unattended multi-hour runs — work list for the cloud session below.
- **Operator's viability bar: $1–2 per multi-hour run.** Achievable config
  identified (worker local + evaluator Haiku + Opus only for init/synthesis
  ≈ **$1.10 / 20-cycle run**); certification command below.

## Environment as configured

| Item | Value |
|---|---|
| Ollama | 0.24.0, loopback only (no `OLLAMA_HOST`) |
| Ollama env (User scope) | `OLLAMA_CONTEXT_LENGTH=32768`, `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_NUM_PARALLEL=3`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_FLASH_ATTENTION=1` |
| Models pulled (exact) | `qwen3.5:9b` (6488c96fa5fa, 6.6GB), `qwen3.5:4b` (2a654d98e6fb, 3.9GB), `gpt-oss:20b` (17052f91a42e, 13GB) |
| gemma4:12b | **NOT pulled** — registry returns 412: requires Ollama > 0.24.0. Follow-up: upgrade Ollama, pull, run its reader leg. |
| SearXNG | container on :8888, JSON format enabled, verified (18 results on test query); `search.searxng_base_url` set in config.yaml |
| Playwright/chromium | not installed (optional; visual-profile captures unavailable) |
| .env | `ANTHROPIC_API_KEY` (operator-supplied), `OLLAMA_AUTH=ollama` |
| Tests | 86/86 pass (after Windows lock fix, commit 518600f) |
| Preflight (`check_local_backend.py`) | PASS for qwen3.5:9b, qwen3.5:4b, gpt-oss:20b — JSON compliance, auth isolation (only `Bearer ollama` on the wire), `endpoint: local, usd: 0` ledger attribution |

## Validation run (handoff step 3) — run `20260610-142033-5b44`

| Acceptance item | Result |
|---|---|
| Readers at `endpoint: local`, `usd: 0` | ✅ 14+ reader sessions, all local, $0 |
| Non-zero reads per worker cycle | ✅ cycle 2: 12–14 reads |
| Per-cycle cost ≪ $2 | ✅ ~$0.45/cycle (worker Sonnet + evaluator Opus) |
| kill -9 + `--resume` | ✅ twice: stale-lock takeover after hard kill; live-lock refusal of a concurrent driver (both exercising the new Windows `_pid_alive`) |
| Conclusive finish / partial report | ❌ halted 3× on invariant 3 — see Finding 1 |

Total spend: $1.32 committed. Run dir preserved.

## Bake-off results (Opus judge; `evals/results/*/scores.json`)

Pre-fix legs (engine at 518600f), `--subset quick` (3 questions), caps
1h/$2.50/8-cycles per question:

| Leg | Worker | Scored | mean_overall | Spend | Verdict |
|---|---|---|---|---|---|
| baseline | Sonnet 4.6 | 1/3 | **8.0** (gen-evbattery: conclusive, 3 cycles, 34 local reads, citations resolve) | $2.31 | pipeline proven; sci+vis lost to Finding 1 |
| worker-qwen35 | qwen3.5:9b local | 0/3 | — | $0 | **unsuitable — protocol**: Ollama compat layer omits thinking `signature` (transport failure), unparseable JSON, malformed ids. Not fixable by prompts. |
| worker-gptoss | gpt-oss:20b local | 0/3 | — | $0 | **near-miss — discipline**: spoke protocol fine; failed read-gate citation rules (same class as Sonnet's sci/vis failures) |

Reader legs (qwen3.5:9b/4b, gemma4, gpt-oss as readers) were **deferred by
operator decision**: pre-fix they could only score ~1/3 questions each at
~$5/leg. Rerun them post-fix, cheaply, with a local worker.

Post-fix verification (engine at 7a93caa), in flight at time of writing:

- `baseline-postfix-sci`: worker resolved q-001/q-002/q-003 in 3 clean
  fail-and-deepen cycles ($1.73) — **the fixes work** — then the leg was lost
  to Finding 2 (CLI crash + hang), not to engine logic. Run dir is resumable.
- `baseline-postfix-vis`: apparent repeat of Finding 2 (no scores; check
  `runs/bakeoff-baseline-postfix-vis.log`).
- `worker-gptoss-postfix` (the local-worker rescue test) and
  `worker-haiku-postfix`: running; results will land in `evals/results/`.

## Fixes made locally (operator-approved, on this branch — review please)

1. **518600f** — `src/runspace.py` `_pid_alive`: `os.kill(pid, 0)` is not a
   probe on Windows (it TerminateProcess-es live pids; raises plain OSError on
   dead ones). Replaced with a `SYNCHRONIZE`/`WaitForSingleObject(0)` probe;
   refuses lock takeover when unsure. Both lock tests made platform-portable.
   Validated live twice (stale takeover + concurrent-driver refusal).
2. **7a93caa** — worker prompt + scientific profile:
   - The read-gate was enforced (`merge_sources` vs `read_urls`) but never
     stated in the prompt — every worker model failed it naturally by citing
     canonical DOI/PubMed URLs for papers read via mirrors. Now stated as a
     hard rule.
   - Scientific profile: on 403 (PubMed/NEJM block automated readers on this
     network), retry PMC → Europe PMC → journal OA page; register the URL
     actually read.
3. **57ce1e5** — `scripts/smoke_test.ps1`: operator's standard 30-minute
   fix-validation loop (reference questions, tight caps, score comparison).

## Findings for the cloud session (priority order)

1. **[CRITICAL] Session hang on CLI-transport death.** The Claude CLI
   subprocess can die mid-session on Windows (`0xC0000409` fail-fast in the
   SDK message reader, observed twice within an hour). The engine's awaiting
   session then hangs **forever** — driver breakers only run between sessions.
   Fix: hard wall-timeout around the SDK session await in `sessions/base.py`
   (e.g. `asyncio.wait_for` with a per-role ceiling from config) → typed
   SessionError → existing retry/resume machinery takes over. Without this,
   unattended multi-hour runs are not viable.
2. **Unledgered mid-flight spend.** A session that dies before completing
   never reaches the ledger, but Anthropic billed its tokens. The budget
   breaker is blind to that spend. Consider ledgering a provisional entry at
   session start (reconciled on completion) or persisting partial usage from
   the stream.
3. **Local-endpoint thinking/signature handling.** Ollama's `/v1/messages`
   does not return thinking signatures; multi-turn worker sessions against
   local endpoints die with "Missing required field: 'signature'". Disable or
   strip thinking blocks for `endpoint: local` sessions in `sessions/base.py`
   — this likely makes qwen-class models viable workers again.
4. **Engine-level OA-mirror fallback** in `read_source` (the 7a93caa prompt
   guidance is the v1; a fetch-layer 403→PMC/EuropePMC retry chain is robust
   to models ignoring guidance).
5. **`--evaluator-model` / `--evaluator-endpoint` flags** for
   `evals/run_evals.py` (operator cost bar requires evaluator off Opus;
   currently worked around with config copies in `runs/config-*.yaml`).
6. Review commits 518600f, 7a93caa, 57ce1e5.

## Routing recommendation + cost (operator bar: $1–2 per multi-hour run)

Measured per-session costs: initializer (Opus) ~$0.07; worker Sonnet
~$0.27–0.45/cycle; evaluator Opus ~$0.11–0.18/cycle; synthesizer (Opus)
~$0.30–0.50; readers local $0.

| Config (20-cycle run) | Worker | Evaluator | Est. total | Notes |
|---|---|---|---|---|
| Handoff default | Sonnet | Opus | ~$8–10 | quality anchor |
| Worker-local only | gpt-oss:20b | Opus | ~$3.30 | above bar |
| **Recommended target** | **gpt-oss:20b** | **Haiku 4.5** | **~$1.10** | `runs/config-budget.yaml`; init+synth stay Opus |
| Aggressive | gpt-oss:20b | local | ~$0.47 | judgment risk unmeasured |

Certification (run after the in-flight legs finish; ~$1–2 because it runs at
target prices):

```powershell
.venv\Scripts\python.exe evals/run_evals.py --subset quick `
  --config runs/config-budget.yaml --max-wall-hours 1 --max-budget-usd 2.5 `
  --max-cycles 8 --out evals/results/budget-config
```

Compare `mean_overall` to baseline's 8.0. Evaluator A/B variant:
`runs/config-evalhaiku.yaml` isolates the evaluator change.
Wall-clock note: local workers are slower — multi-hour becomes overnight for
deep questions; that is the currency traded for $0 worker cost.

## Known constraints honored

- Judgment (evaluator/synthesizer/judge) stayed on cloud Opus throughout the
  measured legs; the recommended config moves the **per-cycle evaluator** to
  Haiku by explicit operator decision (2026-06-10) under the cost bar.
- `usd: 0` local ledger attribution verified at preflight and in live runs.
- No real `sk-ant-*` credential ever reached the local endpoint (recording
  proxy, every preflight).
