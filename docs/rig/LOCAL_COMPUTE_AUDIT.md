# True Research — Local Compute Audit (2026-09-15)

**Target rig:** 2× RTX A4000 (16 GB each, Ampere, no FP8, PCIe/no NVLink) + 384 GB DDR4, Linux.
**Sources:** repo forensics (config/docs/DECISIONS/ledgers of 89 runs), Sept-2026 model landscape,
Sept-2026 serving-stack research. Estimates are marked; everything else is measured or verified.

---

## 1. What we ran before (and why it stopped)

| Fact | Evidence |
|---|---|
| Production local model: **`gpt-oss-20b-32k`** — Ollama Modelfile variant of `gpt-oss:20b` with `num_ctx 32768` | `config.yaml:216-220`, `config.local-hybrid.yaml:286-295` |
| Roles held locally: worker (single-shot query-gen/compose), reader_subagent, compose, per-cycle evaluator. Cloud Opus only for initializer / final gate / synthesizer / verifier ("Opus RARE") | `DECISIONS.md:42`, local-hybrid example |
| Hardware it was tuned for: one **16 GB RTX 5070 Ti**, 64 GB RAM, Windows, Ollama 0.30.7 (0.24 threw fatal `'signature'` errors — docs' "≥0.14" floor is wrong) | `docs/archive/LOCAL_SETUP_REPORT.md` |
| Runner-up `qwen3.5-9b-32k` lost the bake-off: 9 of 17 smoke runs crashed | `evals/results/*/scores.json` |
| Agentic local workers **closed empirically** (3 distinct failure modes in one day) → **pipeline-worker mode** was built so the model never types a URL or invents a source id | `docs/PIPELINE_WORKER_SPEC.md`, `DECISIONS.md:43` |
| Certified: **7.2/10 @ $1.11** (2026-06-11); biggest local run **5.4 h, 922 sessions (738 local), $1.10** | `evals/results/cert-final`, run `20260616-073642-8443` |
| **Retired 2026-06-16 for speed, not quality**: local reader median **103.8 s/page** vs DeepSeek Flash **5.3 s** (~20×), Haiku 26.6 s | 2,626 vs 3,188 ledgered reader sessions; commit `7a34f4a` |
| Base config went all-Anthropic 2026-07-01 for fresh-clone onboarding; local posture preserved as `docs/examples/config.local-hybrid.yaml` | commit `ce08c69` |

**The speed post-mortem the old team never wrote:** the 2,626 local reads averaged **6.9k input / 2.2k output tokens**. A `ReaderOutput` JSON is ~300–600 tokens — the other ~1.6k per read was **gpt-oss reasoning** (medium effort by default; `disable_thinking` was only ever set on `deepseek_flash`/`groq`, never on `local`). Add `OLLAMA_NUM_PARALLEL=3` contention on one card and 100 s/read follows. This is fixable, not intrinsic.

**Still present and tested (nothing was deleted):** prompted-JSON structured-output path for non-first-party endpoints (`base.py:287-292`), `MAX_THINKING_TOKENS=0` injection, per-session env injection (hybrid mixing), `scripts/check_local_backend.py` recording-proxy auth check, `--volume local`, `is_full_local()` loud warning, the bake-off harness (`evals/run_evals.py` per-invocation model overrides), the two-part compose format built around local parse failures.

## 2. Gaps a revival must close (repo)

1. **`-32k` Modelfiles are not in the repo** — only prose describes them (moot if we leave Ollama; see §4).
2. **`reader.max_page_chars` = 60,000** (raised 2026-06-29, after local retired) — ~15k tokens; overflows a 32k local context with prompt + JSON. Either bigger `num_ctx` (KV budget!) or a lower per-posture cap.
3. **`local` endpoint has no `fallback:`** — a dead local server hard-fails the run, unlike deepseek/qwen.
4. **Web UI has no local launch path** (`launch_api.py` presets: cheap or anthropic only).
5. **`--volume local` overrides all four volume roles at once** — no "local reads + cloud compose" mix; the `--cloud-reads` per-run toggle promised in `7a34f4a` was never built.
6. Stale docs: RUNBOOK model table (never-run models), Ollama floor, `.env.example` (missing DEEPSEEK/GROQ/LITELLM/SERPER/DASHSCOPE), DECISIONS has no entry for groq/qwen/LiteLLM/`disable_thinking`, local-hybrid example's reader comment says "reads are DeepSeek Flash".
7. `groq` has no fallback while sitting on a proxy the config itself calls "often down".

## 3. Linux migration — mostly done already

| Area | Status |
|---|---|
| CI | Already `ubuntu-latest` + `windows-latest` matrix, green |
| Detached launcher | Branched: `start_new_session=True` on POSIX (`launcher.py:163-168`), tested |
| PID probe | Branched: `os.kill(pid, 0)` on POSIX (`runspace.py:85-117`) |
| `_atomic_write` share-lock retry | Windows-only problem; dead branch on Linux (harmless) |
| Line endings / paths | `.gitattributes` `eol=lf`; `pathlib` throughout; no drive-letter logic |
| Packaging | Pure Python, `claude-agent-sdk==0.2.95`; heavy extras import-guarded |
| **To do** | `scripts/smoke_test.ps1` → `.sh` twin; systemd units for the serving stack; SearXNG/LiteLLM are already Docker one-liners |
| Driver/CUDA | R615 (615.71.09) supports Ampere; CUDA 13.4 no longer bundles the driver — install `nvidia-driver-615` separately; NVIDIA Container Toolkit 1.20 if containerized |

## 4. Serving stack decision

**Drop Ollama for this workload** (verified in its source, Sept 2026): no `/v1/messages/count_tokens` (Claude Code calls it → 404 → degraded handling, open issue), `tool_choice` ignored, no per-request context, and **no MoE expert-in-RAM offload** (only whole-layer spill) — it cannot use the 384 GB.

**Use `llama-server`** (b10988): native `/v1/messages` + `count_tokens`, `--n-cpu-moe N` / `-ot "exps=CPU"` for experts in DDR4, `-dev CUDA0|CUDA1` per-process GPU pinning, `-np 4 -c 131072 --kv-unified-per-slot 32768` for four concurrent 32k slots, `-ctk q8_0 -ctv q8_0`, `--jinja`, `--reasoning-budget 0` / template kwargs for non-thinking reads. Two systemd units (reader on GPU0, judgment on GPU1) behind **llama-swap** (v255; proxies `v1/messages` + `count_tokens`, routes on the `model` field) as the single `ANTHROPIC_BASE_URL`. No LiteLLM hop.

**vLLM** (v0.29, native `/v1/messages`, xgrammar JSON) only if batched reader throughput needs the 3–4× it delivers on short prompts; on Ampere that means AWQ/GPTQ (Marlin) and TP=2 over PCIe (works, ~85–95% efficiency on dual-3090 reports). llama.cpp handled 43k-token prompts where vLLM was capped at 16k in one bake-off — long-page reads favour llama.cpp.

**Engine impact:** minimal. The engine's prompted-JSON path already bypasses the SDK's structured-output mechanism (which is a synthetic tool + Ajv + 5 retries, not `output_config`), so local JSON stays engine-parsed exactly as before. Config work is new `endpoints:` entries + a posture file.

## 5. Model shortlist for this rig (Sept 2026)

Framing: 32 GB is **two 16 GB cards** — ≤13 GB weights run one-instance-per-GPU (data-parallel, best reader topology); bigger models layer-split (`-sm layer -ts 1,1`, no speedup) or TP=2 in vLLM. A4000 ≈ 0.53× an RTX 3090 (measured llama-bench).

| Role | Primary | Why | Fallback |
|---|---|---|---|
| **Reader** (500× ≤32k, JSON, no tools) | **Gemma 4 26B-A4B** (QAT Q4_0 ~15 GB → one per GPU) | Lowest grounded-hallucination of any open model (HHEM **5.2%**), IFEval 98.5, 3.8B active | **Qwen3.6-35B-A3B** — best measured extraction accuracy (SOB 0.828, above GPT-5.4) but 19.5 GB Q4 → split/IQ3; Omniscience 50% |
| **Per-cycle evaluator / verifier** | **Qwen3.8-27B** (thinking; ~17 GB Q4 → layer-split, or IQ3 on one card) | Best ≤31B open on IFBench 79.5, AA-LCR 82, hallucination **30.3%** (best in class) | Gemma 4 31B (IFEval 98.9, Arena #1 ≤31B open — but 85% Omniscience) |
| **Synthesizer** (10–20k-word cited report) | Qwen3.8-27B non-thinking (262K ctx, long output) | fits VRAM; est. 20–40 t/s split | **DeepSeek V4-Flash-0731 UD-Q8 (162 GB) in DDR4** — MIT, AA-LCR 79.7; est. 10–20 t/s; or Inkling-Small (Apache, IFBench 82) |
| Avoid | gpt-oss-20b (**worst extraction 0.693** — this was our old reader!), Muse Glimmer (28% prompt-injection ASR — bad for untrusted pages), Ollama-era 9B/4B | | |

**DDR4 hybrid MoEs** (experts in RAM): decode ~10–30 t/s depending on **memory channel count** (8-ch DDR4 ≈ 70–110 GB/s effective; dual-channel ×0.4). Prefill on offloaded experts costs 25–130 s per 32k prompt → **not for the reader role**, fine for one synthesizer call per run. Run `llama-bench` before committing.

**Does the rig close the 20× gap?** Estimate: A4B/A3B MoE reader, one instance per A4000, non-thinking, ~500-token outputs → **~8–15 s/read** (vs 103.8 s before, 5.3 s Flash) at $0 and fully private — within 2–3× of Flash. Dense 27B judgment roles on the other card. Verify with the bake-off.

## 6. Proposed target architecture (for the brainstorm)

- **GPU0:** `llama-reader` — Gemma 4 26B-A4B (or Qwen3.6-35B-A3B IQ3), 4 slots × 32k, q8 KV, non-thinking. Serves `reader_subagent`, `compose`, query-gen.
- **GPU1:** `llama-judge` — Qwen3.8-27B (IQ3/Q4 layer-split if needed), 2 slots, thinking on. Serves `evaluator`, `verifier`, and optionally `synthesizer`.
- **DDR4 (optional third unit, on-demand via llama-swap):** DeepSeek V4-Flash Q8 for synthesis when quality > speed.
- **Cloud (optional):** Opus for initializer / final gate — or fully local with the loud warning, operator's choice per run.
- **Config:** endpoints `local_reader`, `local_judge`, `local_big` (+ `fallback: anthropic` optional per privacy posture); posture `docs/examples/config.local-rig.yaml`; `--volume local` re-pointed; a `--cloud-reads` per-run toggle; per-posture `reader.max_page_chars`.
- **UI:** "Local" preset when llama-swap health check passes.
- **Certification:** reuse `evals/run_evals.py` (3-question batch per candidate model) + `scripts/check_local_backend.py` adapted to llama-swap's bearer token.

## 7. Open questions for the operator

1. **CPU model / DDR4 channel count** — decides whether the big-MoE synthesizer is 10 t/s or 30 t/s.
2. **Privacy posture:** fully local (halt on local failure) vs hybrid (fall back to cloud with a logged DECISION)?
3. Linux distro + whether the rig is headless (systemd) or a desktop.
4. PCIe layout (both cards x16? gen 3/4?) — affects layer-split and TP=2 viability.
5. Keep Opus for the two judgment bookends, or go fully local for the head-to-head story?
