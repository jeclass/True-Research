"""DEPTH wave (COMPREHENSIVE_RESEARCH_SPEC item 4).

When BREADTH concludes (the seed tree is resolved), the driver deliberately
re-investigates the run's most load-bearing findings before VERIFY/SYNTHESIZE.
The selection is deterministic (top-N factual findings by confidence) and the
question text is a fixed template — NO model call, $0 — so this stays within the
driver's contract: it *seeds work*, and the existing worker/evaluator machinery
does the investigating. DEPTH differs from the evaluator's gap-questions: the
evaluator opens questions for what's MISSING; DEPTH hardens what the report will
LEAD with, insisting on primary sources and cross-validation before VERIFY tries
to refute those same claims.
"""

from __future__ import annotations

from src.errors import StateError
from src.runspace import Runspace
from src.settings import Settings
from src.state import OpenQuestion

# Nudges the worker toward primary-source re-investigation + cross-validation of
# the SAME topic, rather than restating the finding it already has on file.
_DEPTH_TEMPLATE = (
    'Deepen and cross-validate the established answer to: "{q}". Re-investigate '
    "from primary sources where possible; require at least two independent "
    "corroborations for each key figure; re-verify specific numbers against the "
    "primary source and flag any that cannot be independently confirmed. Do not "
    "restate the existing finding — strengthen it, or correct it if it does not hold."
)


def seed_depth_questions(run: Runspace, settings: Settings) -> int:
    """Append DEPTH questions for the top-N highest-confidence factual findings.

    Idempotent w.r.t. a finding's question (skips a finding that already has a
    depth child), so a crash between seeding and the wave flip can't duplicate
    work on resume. Returns the count seeded; 0 means there is nothing worth
    deepening and the driver finishes instead of entering the DEPTH wave.
    """
    findings = run.load_findings()
    # Per-question early-stopping (roadmap quick win): optionally skip leads already
    # cross-validated by >= N sources, so DEPTH hardens the under-corroborated leads
    # that need it. skip_n=0 (default) deepens the top-N regardless, as before.
    skip_n = settings.waves.skip_corroborated_min_sources
    factual = sorted(
        (
            (slug, m)
            for slug, (m, _body) in findings.items()
            if m.track == "factual"
            and not (skip_n and len(m.source_ids) >= skip_n)
        ),
        key=lambda t: t[1].confidence,
        reverse=True,
    )[: settings.waves.depth_findings]
    if not factual:
        return 0

    questions = run.load_questions()
    existing_ids = {q.id for q in questions.root}
    already_deepened = {q.parent_id for q in questions.root if q.created_by == "depth"}

    seeded = 0
    for _slug, meta in factual:
        parent_id = meta.question_id
        if parent_id in already_deepened:
            continue
        try:
            parent = questions.get(parent_id)
        except StateError:
            # The finding's parent question is absent from open_questions.yaml.
            # The old bare-except fallback silently seeded a useless question
            # (text = the raw id) at a RESET depth of 1 — losing the tree-depth
            # bound, so an orphaned deepen could fragment past max_depth, with no
            # record. That violates invariant 8 (log tradeoffs, never silently
            # absorb). Questions are status-changed, not deleted, so this is a
            # defensive path that should be loud if it ever fires: log it and skip
            # rather than fabricate a bound-breaking, topic-less question (audit
            # completeness gap, 2026-06-30).
            run.log_decision(
                f"DEPTH: skipped deepening a finding for question {parent_id!r} — "
                "its parent is no longer in open_questions.yaml (pruned/closed), so "
                "no bounded, meaningful depth question can be formed."
            )
            continue
        qtext, depth = parent.question, parent.depth + 1
        new_id = _unique_id(parent_id, existing_ids)
        questions.root.append(
            OpenQuestion(
                id=new_id,
                question=_DEPTH_TEMPLATE.format(q=qtext),
                status="open",
                priority=2,  # high, so workers pick deepening promptly
                parent_id=parent_id,
                created_by="depth",
                track="factual",
                depth=depth,
            )
        )
        existing_ids.add(new_id)
        already_deepened.add(parent_id)
        seeded += 1

    if seeded:
        run.save_questions(questions)
    return seeded


def _unique_id(base: str, existing: set[str]) -> str:
    candidate = f"{base}-deep"
    n = 2
    while candidate in existing:
        candidate = f"{base}-deep{n}"
        n += 1
    return candidate
