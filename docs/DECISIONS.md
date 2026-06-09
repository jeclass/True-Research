# Decisions log

One line per non-obvious choice: what, why, alternative rejected.

- 2026-06-09 — Build at the repo root (`True-Research/` is the project root) — §2's `marathon-research/` is the project folder itself, and nesting adds path depth for nothing; rejected: a `marathon-research/` subdir inside the repo.
- 2026-06-09 — Renamed `CLAUDE (2).md` → `CLAUDE.md` (git mv) — §2 names the file `CLAUDE.md` and the space-laden name breaks tooling; rejected: keeping a duplicate copy (divergence risk).
- 2026-06-09 — Project venv at `.venv/` for all deps — system pip is Debian-managed and aborted on a PyJWT uninstall; rejected: `--ignore-installed` into system site-packages (fragile, pollutes the container).
- 2026-06-09 — Engine sessions will always pass `setting_sources=[]` + an explicit `system_prompt` string — SDK default (None) loads user/project/local settings and CLAUDE.md, violating the amnesia invariant (§3.1); rejected: relying on SDK defaults.
- 2026-06-09 — Secrets are loaded from `.env` into the frozen Settings object and injected per spawned session via `options.env`; never exported into the driver's `os.environ` — child processes inherit parent env and `options.env` cannot *remove* inherited keys, so a process-global key would leak to local-endpoint sessions; rejected: `load_dotenv()` into process env.
- 2026-06-09 — Budget breakers trust `ResultMessage.total_cost_usd` (client-side estimate per docs) — breakers need a conservative tripwire, not billing-grade truth; rejected: polling the Usage & Cost Admin API (extra dep, latency, admin-key requirement).
- 2026-06-09 — State hash = SHA-256 over sorted (relpath, file-sha) pairs of `open_questions.yaml` + `findings/` only (per §3.5) — hashing the whole run dir would let PROGRESS/ledger writes mask a stall; rejected: hashing the entire run dir.
