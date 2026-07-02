# The two-axis model: profiles × lenses

Built 2026-06-11 (operator-directed). Records an architecture decision and the
community lens as shipped, for the cloud session's review.

## Two orthogonal axes

The engine composes a run from **two independent axes**:

| Axis | Question it answers | Cardinality | Sets | Members |
|---|---|---|---|---|
| **Domain profile** (`src/profiles/`) | *what kind of sources, judged how?* | exactly **one** (`--profile`) | worker tool set + evaluator rubric + worker guidance | general · scientific · visual · **legal** (v1 scaffold) |
| **Evidence lens** (`src/lenses/`) | *what additional evidence class, kept separate?* | **zero or more** (`--lens`, repeatable) | an extra search channel on its own `track` + a quarantined report section | **community** (first) |

They are perpendicular by design. `--profile scientific --lens community` asks
"what do the trials establish **and** what do patients report" — with a hard
wall between the two. Making community a fourth *profile* would have forced an
either/or (you'd lose the scientific rubric to get the community lens); the lens
axis makes it additive instead.

## The `track` quarantine (the load-bearing invariant)

Every question and finding carries `track: factual | community` (default
`factual`). This is the wall:

- Community-track questions route to the lens's search providers, not the
  profile's (`pipeline.py`, guarded on `track != "factual"`).
- Their findings inherit `track="community"`.
- The **synthesizer never shows community findings to the factual model** — it
  passes `only_tracks={"factual"}` to the findings digest. The factual Opus
  synthesis is composed *exclusively* from factual findings; it cannot fold
  anecdote into a factual claim because the anecdote isn't in its context.
- Community findings are **engine-appended** into a separate
  "Community & practitioner perspective" section with an explicit epistemic
  caveat (sentiment, self-selected, unverified). The citation pass still runs
  over the whole report, so every `[src-…]` resolves — community claims remain
  attributed to the exact thread they came from (`require_reads` unchanged).

Result: studies and lived experience appear in one report, cleanly separated,
neither contaminating the other. The reader's own credibility rubric already
scores forum content low, so it self-segregates; the track tag makes it hard.

## Default-path safety

Everything above is **default-off**. `lenses: []` (the config default) means a
normal run produces only factual-track findings, and every touched function is
guarded to be byte-identical in that case (verified:
`test_synthesizer_no_community_section_when_none`, and the full suite green
before/after). The community lens adds capability without changing any existing
behavior.

## Files

- `src/lenses/__init__.py` — `Lens` ABC + registry (`get_lens`, `lens_for_track`).
- `src/lenses/community.py` — `CommunityLens`: forum/Q&A search provider
  (SearXNG site-scoped to reddit/HN/StackExchange/Quora), seed questions, the
  report section title + framing.
- `src/state.py` — `track` on `OpenQuestion` and `FindingMeta`.
- `src/settings.py` — `lenses: list[str]` + name validation; `--lens` CLI in
  `driver.py` and `evals/run_evals.py`.
- `src/sessions/initializer.py` — seeds lens questions when active.
- `src/sessions/pipeline.py` — community-track routing + finding stamping.
- `src/sessions/synthesizer.py` — factual/community split + quarantined section.

## Validated

- Unit: 9 tests in `tests/test_lenses.py` (registry, settings validation,
  digest filter, quarantine assertion, default-off guard).
- Live: the community provider returns real subreddit threads
  (`r/RobotVacuums` for a robot-vacuum-longevity query).
- **Not yet validated end-to-end**: a full `--lens community` run producing a
  two-section REPORT.md needs a real synthesizer pass + GPU time (currently
  occupied by the budget certification). That's the one remaining check before
  declaring the lens production-ready — recommended as the first post-
  certification run.

## Future work (for the cloud session)

1. **Legal profile** (`src/profiles/legal.py`) is a v1 scaffold — works on
   general web search with a primary-law-first rubric. Add real legal
   connectors (CourtListener / Caselaw Access Project / official statute DBs)
   as MCP search providers, the way `scientific.py` adds PubMed/OpenAlex.
2. **Evaluator track-awareness**: the evaluator currently sees all findings.
   Consider judging community findings on a coverage/diversity-of-voices
   sub-rubric rather than the factual rubric.
3. **Subreddit targeting**: the lens scopes to community hosts broadly; a
   topic→subreddit map would sharpen the "specialized subgroups" retrieval.
4. **More lenses**: news/recency, expert-interview — same pattern.
