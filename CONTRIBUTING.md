# Contributing to True Research

Thanks for your interest. This is a focused single-operator tool, not a
framework — contributions that keep it simple and honest are the most welcome.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # 288 tests, fully offline (no network, no API keys)
```

The test suite is **hermetic**: it never hits the network or spends API credits.
Keep it that way — mock external calls; a test that needs a live endpoint doesn't
belong in the default suite.

## Ground rules

- **The invariants in `CLAUDE.md` §3 are non-negotiable.** No silent failures;
  every claim traceable to a source; circuit breakers before every session;
  atomic state writes; resumable. If a change would weaken one, it needs a very
  good reason and a loud, tested surface.
- **TDD.** Write the failing test first. PRs that change behavior without a test
  that would have caught the old behavior will be asked for one.
- **Never commit secrets.** Keys live in `.env` (gitignored). CI runs a
  full-history secret scan (gitleaks) on every push; it must stay green.
- **The driver stays dumb.** `driver.py` contains zero prompt text and zero model
  calls of its own — all cognition lives in `src/sessions/`. Keep that separation.
- **Match the surrounding style.** Comments state constraints and hard-won facts,
  not narration.

## Where things live

See the "Architecture" section of the [README](README.md) and the full build
spec in `CLAUDE.md`. Adding a research domain = adding one `Profile`
(`src/profiles/`); the loop, state, and invariants never change.

## Pull requests

Keep them focused. Run `pytest -q` (green on Linux + Windows, 3.11 & 3.13 in CI)
and describe what you changed and why. For anything touching cost, search, or the
session prompts, note the impact on a real run if you can.
