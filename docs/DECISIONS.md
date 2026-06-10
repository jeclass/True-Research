# Decisions log

One line per non-obvious choice: what, why, alternative rejected.

- 2026-06-09 — Build at the repo root (`True-Research/` is the project root) — §2's `marathon-research/` is the project folder itself, and nesting adds path depth for nothing; rejected: a `marathon-research/` subdir inside the repo.
- 2026-06-09 — Renamed `CLAUDE (2).md` → `CLAUDE.md` (git mv) — §2 names the file `CLAUDE.md` and the space-laden name breaks tooling; rejected: keeping a duplicate copy (divergence risk).
- 2026-06-09 — Project venv at `.venv/` for all deps — system pip is Debian-managed and aborted on a PyJWT uninstall; rejected: `--ignore-installed` into system site-packages (fragile, pollutes the container).
- 2026-06-09 — Engine sessions will always pass `setting_sources=[]` + an explicit `system_prompt` string — SDK default (None) loads user/project/local settings and CLAUDE.md, violating the amnesia invariant (§3.1); rejected: relying on SDK defaults.
- 2026-06-09 — Secrets are loaded from `.env` into the frozen Settings object and injected per spawned session via `options.env`; never exported into the driver's `os.environ` — child processes inherit parent env and `options.env` cannot *remove* inherited keys, so a process-global key would leak to local-endpoint sessions; rejected: `load_dotenv()` into process env.
- 2026-06-09 — Budget breakers trust `ResultMessage.total_cost_usd` (client-side estimate per docs) — breakers need a conservative tripwire, not billing-grade truth; rejected: polling the Usage & Cost Admin API (extra dep, latency, admin-key requirement).
- 2026-06-09 — State hash = SHA-256 over sorted (relpath, file-sha) pairs of `open_questions.yaml` + `findings/` only (per §3.5) — hashing the whole run dir would let PROGRESS/ledger writes mask a stall; rejected: hashing the entire run dir.
- 2026-06-09 — Sessions return structured output (`output_format` json_schema); engine code performs ALL state-file mutations and withholds Write/Edit from every session — invariants 3/6 become code-enforced; rejected: letting models write YAML/JSON state via Write tool (format drift corrupts state).
- 2026-06-09 — `created_by` gains "worker" — §6 has workers spawning child questions on fragmentation, §4's enum lacked it; rejected: mislabeling worker children as evaluator-created.
- 2026-06-09 — Fragmented questions: parent marked resolved without a finding, children carry it forward, decision logged; rejected: leaving parent open (worker would re-pick it forever).
- 2026-06-09 — Ledger recording moved into the session layer (base.run_role_session records success AND failure) — a session that errors after spending tokens still accounts its spend; rejected: driver-side recording from returned results (loses spend on session exceptions).
- 2026-06-09 — `cached_tokens` = cache_read + cache_creation input tokens summed; `usd` from total_cost_usd covers the rate difference; rejected: separate columns (schema §4 has one field).
- 2026-06-09 — Output schemas avoid numeric min/max JSON-schema constraints (unsupported by structured outputs); ranges (priority 1-5, confidence 0-1, credibility 0-100) validated in engine code with typed errors; rejected: silent clamping.
- 2026-06-09 — Synthesizer with zero findings writes an honest "nothing to report" report with NO model call; rejected: paying Opus to say nothing.
- 2026-06-09 — Evaluator pass while unresolved questions remain is force-failed by the engine with a logged decision (belt-and-braces on invariant 2); rejected: trusting the model's passed flag alone.
- 2026-06-10 — Worker target selection prefers orphaned in_progress questions over open ones — in_progress at cycle start can only mean a crashed/errored prior attempt (every worker exit path moves the status), and the smoke run showed an orphan starving behind open questions; rejected: open-first with in_progress fallback.
