# True Research — Local Compute Rig: Setup Handoff for a fresh Claude Code session

You are a Claude Code session on Josh's AI compute rig. Your job: bring up a
**local deep-research mode** for True Research on this machine, then certify it.
Read this whole file first, then `docs/rig/LOCAL_COMPUTE_AUDIT.md` (the audit
that produced this plan). Work in phases; stop and ask Josh at the marked gates.

## 0. What this project is (60 seconds)

True Research is a deep autonomous research engine (public repo
https://github.com/jeclass/True-Research, MIT). A deterministic driver loop runs
many short **amnesiac** Claude-Agent-SDK sessions (initializer → worker/reader
fan-out → evaluator → verifier → synthesizer) against state on disk, producing
a 10–20k-word report where every claim resolves to a source the engine actually
read. It talks to any model through the **Anthropic Messages API shape**
(`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`, injected per spawned session —
so one run can mix backends per role). Read `CLAUDE.md` for the invariants.

Current state: **v1.2**, 347 tests green on Linux + Windows CI, last commit on
`main` is the scored head-to-head (True Research placed 2nd of 3 vs Claude and
Gemini deep research, won the honesty axis). Local models were used in June
2026 (see audit §1) and retired for **speed**, not quality. This rig fixes speed.

## 1. Hardware + goal

- 2× NVIDIA RTX A4000 — 16 GB each (Ampere, **no FP8**, PCIe, no NVLink)
- 384 GB DDR4 system RAM (channel count: **ask Josh / check `dmidecode`** — it
  decides whether big-MoE synthesis runs at ~10 or ~30 tok/s)
- Linux (record distro + kernel below)
- Goal: volume roles (reader, query-gen/compose, per-cycle evaluator) on
  local models at $0; judgment bookends optionally on cloud Opus; a fully-local
  posture must also work (with the engine's existing loud warning).

Record what you find here before starting Phase 2:
```
CPU:            <model, cores, DDR4 channels populated>
RAM:            <GB, speed, channels>
GPUs:           <nvidia-smi output: both A4000s visible, driver version>
PCIe:           <lspci -vv: x16/x8 per card, gen>
Distro/kernel:  <cat /etc/os-release; uname -r>
Free disk:      <df -h — need ~100 GB for models, 250 GB if the DDR4 MoE is used>
```

## 2. How to work in this repo (non-negotiable conventions)

- Use the project venv interpreter for everything: `.venv/bin/python -m pytest -q`
  (never bare `python`).
- Commit directly to `main` (project convention). Every commit body ends with
  the `Co-Authored-By` trailer for the Claude model you are.
- Engine changes follow the superpowers flow: `superpowers:brainstorming` →
  spec in `docs/superpowers/specs/` → `superpowers:writing-plans` →
  `superpowers:subagent-driven-development` (fresh implementer per task,
  spec review + quality review per task). TDD: failing test first.
- When you dispatch implementer subagents, tell them explicitly: **"do the work
  YOURSELF — do NOT use the Agent tool"** (a delegation cascade happened once).
- Log every non-obvious decision as one line in `docs/DECISIONS.md`; user-facing
  changes go in `CHANGELOG.md` (add a `## v1.3 — unreleased (local compute)` section).
- **Secrets:** keys live in `.env` (gitignored) or are entered in the web UI Keys
  tab. The repo is PUBLIC with push protection — never paste key values into
  files, logs, or commit messages. `scripts/check_local_backend.py` exists to
  prove real Anthropic credentials are NOT leaking to the local server; run it.
- **Do not run hybrid/local postures inside a broker-managed sandbox** (Claude
  Code on the web) — `docs/SDK_NOTES.md` documents the credential-leak hazard.
  This rig is bare metal, so you're fine; just don't move the work to a sandbox.

## 3. Serving stack decision (from the audit — do not relitigate)

- **Not Ollama.** Verified Sept 2026: no `/v1/messages/count_tokens` (Claude Code
  calls it → 404 → degraded handling), `tool_choice` ignored, no per-request
  context, **no MoE expert-in-RAM offload** (can't use the 384 GB).
- **`llama-server` (llama.cpp), two instances — one per GPU — behind
  `llama-swap`** as the single `ANTHROPIC_BASE_URL`. Native `/v1/messages` +
  `count_tokens`; `--n-cpu-moe`/`-ot "exps=CPU"` puts MoE experts in DDR4;
  `-dev CUDA0|CUDA1` pins a process to a card; slots give concurrency.
- vLLM only if batched reader throughput proves insufficient (Ampere = AWQ/GPTQ
  Marlin only, TP=2 over PCIe works at ~85–95%).
- The engine's prompted-JSON path for non-first-party endpoints
  (`src/sessions/base.py`, `endpoint_is_local`) already parses local JSON
  engine-side — no dependency on local tool-calling. Keep it.

## 4. Model shortlist (Sept 2026; verify exact Hugging Face repo ids yourself — prefer Unsloth `UD-*` GGUFs or Google's QAT GGUFs; do not guess repo names)

| Role | Primary | Fallback | Notes |
|---|---|---|---|
| Reader / compose / query-gen (GPU0) | **Gemma 4 26B-A4B** QAT Q4_0 (~15 GB) — lowest grounded-hallucination of any open model (HHEM 5.2%), IFEval 98.5 | **Qwen3.6-35B-A3B** (best extraction accuracy, SOB 0.828; 19.5 GB Q4 → IQ3 or layer-split) | Non-thinking mode. ~500-token JSON outputs. |
| Per-cycle evaluator / verifier (GPU1) | **Qwen3.8-27B** thinking (~17 GB Q4 → IQ3 on one card or `-sm layer` across both) — IFBench 79.5, AA-LCR 82, hallucination 30.3% | Gemma 4 31B | Don't over-quantize KV on Qwen3.8 at long ctx (q8_0 ok; q4_0 degrades). |
| Synthesizer | Qwen3.8-27B non-thinking (VRAM) | **DeepSeek V4-Flash-0731 UD-Q8** (162 GB, experts in DDR4, mainline llama.cpp) or Inkling-Small | Hybrid MoE prefill on 32k prompts costs 25–130 s/call → never for readers. |
| Avoid | `gpt-oss-20b` (worst extraction score in the benchmark — it was our old reader), Muse Glimmer (28% prompt-injection ASR) | | |

## 5. Phase plan

### Phase 1 — Machine prep (no engine changes)
1. NVIDIA driver R615-series (`nvidia-driver-615`), `nvidia-smi` shows both cards.
   CUDA toolkit only needed if you build llama.cpp from source (recommended:
   `cmake -B build -DGGML_CUDA=ON && cmake --build build -j`), else use
   `ghcr.io/ggml-org/llama.cpp:server-cuda` with NVIDIA Container Toolkit ≥1.20.
2. `git clone https://github.com/jeclass/True-Research && cd True-Research &&
   python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" &&
   .venv/bin/python -m pytest -q` → expect 347 passed.
3. Docker: SearXNG (`docs/RUNBOOK.md` has the one-liner) — needed if no
   `SERPER_API_KEY`; Serper is the primary search when the key is present.
4. Download models (§4). `llama-bench` each candidate on ONE A4000 at 32k
   context and record tok/s (prefill + decode) in `docs/rig/BENCH.md`.
   **GATE 1: report numbers to Josh before proceeding.**

### Phase 2 — Serving stack
1. `llama-swap` config with three models: `reader` (GPU0), `judge` (GPU1),
   optional `big` (DDR4 MoE, on-demand). Example unit for the reader:
   ```
   llama-server -m <gemma4-26b-a4b>.gguf -dev CUDA0 --port 8081 --jinja -fa on \
     -ctk q8_0 -ctv q8_0 -np 4 -c 131072 --kv-unified-per-slot 32768 \
     -ub 2048 -b 2048 --reasoning-budget 0 --api-key "$LOCAL_LLM_TOKEN"
   ```
   (If the build lacks `--kv-unified-per-slot`, use `--no-kv-unified -c 131072 -np 4`.
   For thinking-capable models use `--reasoning-budget 0` or
   `--chat-template-kwargs '{"enable_thinking":false}'` on the READER only.)
   Judge on `-dev CUDA1 --port 8082`, 2 slots, thinking on. For the DDR4 MoE:
   `-ngl 999 --n-cpu-moe <N> --no-mmap`, tune N until VRAM is full.
2. systemd units for llama-swap (:8080) and SearXNG; `curl :8080/v1/messages`
   smoke test with a trivial request; confirm `count_tokens` answers.
3. Put `LOCAL_LLM_TOKEN` in `.env` (never commit).

### Phase 3 — Engine changes (brainstorm → spec → plan → implement)
Known gaps from the audit; design them in the brainstorm, don't skip it:
- `config.yaml`: endpoints `local_reader` / `local_judge` / `local_big`
  (`base_url: http://127.0.0.1:8080`, `auth_env: LOCAL_LLM_TOKEN`,
  `disable_thinking: true` on the reader endpoint, `price_per_mtok` omitted ⇒
  usd 0). Role `model:` values must equal llama-swap model keys (it routes on
  the `model` field). Decide **fallback policy** (fully-local halt vs cloud
  fallback with a logged DECISION) — ask Josh.
- New posture `docs/examples/config.local-rig.yaml`; re-point `--volume local`.
- `reader.max_page_chars` is 60,000 (~15k tokens) — set a per-posture value
  that fits the reader slot's context, or give reader slots 64k.
- Finish the never-built `--cloud-reads` / `--local-reads` per-run toggle.
- Web UI: add `LOCAL_LLM_TOKEN` to `keys_api.KEY_ALLOWLIST` and a "Local"
  preset gated on a llama-swap health check (`src/webui/launch_api.py`).
- `scripts/check_local_backend.py`: point the recording proxy at llama-swap and
  expect `Bearer $LOCAL_LLM_TOKEN` (fail on any `sk-ant` leak).
- `scripts/smoke_test.ps1` → `scripts/smoke_test.sh`.
- Docs: RUNBOOK local section rewrite (Ollama material is obsolete),
  `.env.example`, DECISIONS lines, CHANGELOG v1.3.

### Phase 4 — Certification
1. `evals/run_evals.py` bake-off: for each candidate reader/evaluator pair use
   the `--reader-endpoint/--reader-model/--evaluator-*` overrides; compare
   `scores.json` against the June baseline (cert-final mean 7.2, $1.11) and
   the cheap posture.
2. One comprehensive run on the local-rig posture; record cycles, reads,
   median reader wall-seconds (June local was 103.8 s; DeepSeek Flash 5.3 s;
   target ≤15 s), $ and report stats in `EVIDENCE.md` as "Run 5 — local rig".
   **GATE 2: show Josh before publishing.**

## 6. Kickoff checklist for this session
- [ ] Fill §1 hardware block
- [ ] Phase 1 done, tests 347 green, `llama-bench` numbers in `docs/rig/BENCH.md`
- [ ] GATE 1 with Josh
- [ ] Phase 2 stack up, `check_local_backend.py` passes
- [ ] Phase 3 via superpowers flow, all tests green, pushed
- [ ] Phase 4 certification, GATE 2
