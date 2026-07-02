# Changelog

## v1.1 — unreleased (web UI usability)

- **Two presets.** The launch view offers Quick (~$1, `--cheap --gate opus`) and
  Comprehensive (~$3–5, adds `--comprehensive --verify` — the showcase-run
  config). No DeepSeek key? The server transparently runs the same depth on the
  all-Anthropic backend and the UI says what that costs.
- **Keys panel.** Paste Anthropic/DeepSeek/Serper keys in the dashboard; they're
  written to `.env` and are never displayed or readable back. State-changing
  endpoints now reject cross-origin requests.
- **Report downloads.** `.md` + PDF from the report view and the runs list.
- **Long-paste distill.** Pasting a page of text triggers a one-shot Haiku
  preview — "here's the research question I'll pursue" — editable before any
  run spend; skippable; the full paste still reaches the initializer.

## v1.0 — 2026-07-02 (public-release preparation)

The push from "works on one machine, private repo" to a polished, portable,
open-source deep-research engine with a local web UI. 38 commits; test suite
grew from ~267 to **288**, green on Linux + Windows (Python 3.11 & 3.13) in CI.

### Engine finalization (Phase 1 — certified via a fresh-clone smoke)
- **Runs out of the box with one key.** Base `config.yaml` now routes all roles
  to Anthropic, so a clean clone with only `ANTHROPIC_API_KEY` works; the prior
  local-hybrid posture is preserved as `docs/examples/config.local-hybrid.yaml`.
- **Cross-platform detached launcher + auto-resume supervisor** (`src/launcher.py`)
  replaces the Windows-only PowerShell script; survives a closed terminal and
  auto-resumes until the run finishes.
- **`--question-file` / `--run-id-file`** on the driver — quote-laden questions
  survive shell tokenization, and supervisors learn the run id without scraping.
- **Pip-installable** with a `true-research` console command (`run`, `resume`,
  `ui`, or a bare question) via `pyproject.toml`.
- **CI**: pytest matrix on ubuntu + windows × 3.11/3.13, plus a full-history
  gitleaks secret scan on every push.
- **Final 3-reviewer audit** of everything since the prior audit: 11 confirmed
  findings fixed — span-citation soundness (no cross-cell quote stitching),
  parallel-mode outage/collision semantics, endpoint fallback only on transport
  errors (not parse rerolls), agentic-worker injection defense, config
  fail-loud, and more.

### Roadmap features
- **Span-level citation anchors** — sources carry engine-verified verbatim
  excerpts; the report renders them as checkable quote anchors under each source.
- **Journal-reputation enrichment** — OpenAlex retraction + non-DOAJ flags
  surface to the scientific worker before it cites a paper.
- **Prompt-injection defense** — untrusted fetched page text is fenced so it
  can't redirect the reader/worker/synthesizer.
- **Corroboration-aware verification + depth targeting**; **opt-in parallel
  worker fan-out** for wall-clock.

### Local web UI (Phase 2 — `true-research ui`)
- Zero-build FastAPI + vanilla-JS app on `127.0.0.1`: **launch** runs from a
  form, watch them **live** (spend vs budget, the question tree and findings
  resolving, VERIFIED/REFUTED badges, decisions log), and read the **report**
  with clickable citations + PDF download.
- Read-only over `runs/` state files; a dedicated secret-leak guard test; the
  launch endpoint passes the question via a file (never argv) and validates
  flags against an allowlist; report renderer hardened against `javascript:`
  URLs and raw-HTML injection (caught in security review, fixed + browser-tested).

### Release docs (Phase 3)
- README rewrite (True Research branding, UI screenshots, honest ledger-backed
  cost table), MIT `LICENSE`, `CONTRIBUTING.md`, and `EVIDENCE.md` documenting
  real runs (a $4.65 / 323-page / 97-source conclusive report; the v1.0
  certification run).

### Evidence highlight
`--cheap --gate opus --comprehensive --verify` on a hard applied question ran
**24 cycles, read 323 pages, kept 97 sources, and concluded for $4.65**, with
the full session pipeline firing (initializer → 48 worker + 323 reader → 38
evaluator → synthesizer) and thin sub-questions returned UNVERIFIED rather than
fabricated.

### Still open (not yet done)
- Head-to-head comparison vs hosted deep-research services (two showcase runs in
  flight; needs competitor outputs for a blind scoring).
- Public release itself is **gated**: the repo stays private until an explicit
  go + GitHub push-protection/secret-scanning enabled at flip time.
- Open decision: the zero-config default caps at $2 on the (pricier) all-Anthropic
  posture and returns a partial report; `--cheap` (DeepSeek volume) is the
  cost-optimized path to a full report at ~$2–5.
