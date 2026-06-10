"""Evaluator session (Opus, FRESH context): the default-FAIL quality gate
(CLAUDE.md §6, invariant 2) plus the Phase 3 judgment layer:

- contradiction ADJUDICATION: each contradiction is either ruled on (which
  claim wins and why, weighing credibility/recency/primacy) or sent back as
  a new question — never silently listed;
- tightened stopping criteria: the evaluator sees the run's remaining budget
  and may CLOSE unresolved questions it judges immaterial to the conclusion
  (logged loudly), so fail-and-deepen converges instead of sprawling.

The module writes the verdict file and applies all question mutations
deterministically, and force-fails any pass that contradicts the state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.ledger import Ledger
from src.profiles import get_profile
from src.runspace import PLAN_FILE, Runspace
from src.sessions import common
from src.sessions.base import EvalError, SessionResult, run_role_session
from src.settings import Settings
from src.state import OpenQuestion, Verdict

_ROLE = "evaluator"
_TOOLS = ["Read", "Glob", "Grep"]

_SYSTEM_PROMPT = """\
You are the EVALUATOR — an adversarial quality gate with a fresh context. You
have NO memory of the effort that produced this state and owe it no charity.

START FROM FAIL. Output passed=true ONLY if you can defend, against a hostile
reviewer, that the body of findings conclusively answers the research
question. Absence of evidence = FAIL.

Check, in order:
1. Resolution — is every question resolved by an actual finding (not just
   marked resolved)? Fragmented/blocked questions count against conclusiveness.
2. Traceability — does every factual claim in every finding carry [src-...]
   citations that exist in the source registry? Spot-check claims against
   source titles/notes for plausibility.
3. Contradictions — do findings contradict each other or themselves? For EACH
   contradiction you must do one of two things:
   a. ADJUDICATE it (resolution="adjudicated"): rule which claim stands,
      weighing source credibility, recency, primary-vs-secondary evidence,
      and sample size. State the ruling and reasoning in `adjudication`.
   b. Send it back (resolution="needs_investigation"): when the evidence on
      file cannot support a ruling, say what is missing in `adjudication`
      AND open a matching new_question targeted at resolving it.
4. Source quality — are sources credible, diverse (not one outlet), and recent
   enough for the topic? A conclusion resting on weak sources FAILS.
5. Sufficiency — does the set of findings actually answer the ORIGINAL
   research question, not just the open questions?

Stopping discipline (you will be shown the run's remaining budget):
- Open a new question ONLY if its answer could plausibly CHANGE the report's
  conclusion — not merely enrich it. Max 3 per cycle, priority 1-5,
  parent_id when refining an existing question.
- You may CLOSE unresolved questions that have become immaterial to the
  conclusion (close_questions: id + reason). Use this to prune speculative
  questions — including ones a previous evaluator opened — once the evidence
  shows they no longer matter. Closing is for IMMATERIAL questions only,
  never for hard-but-load-bearing ones.
- As remaining budget shrinks, weigh depth against completion: a sharp,
  well-supported answer to the core question beats an unfinished sprawl.

unmet_criteria: one entry per concrete failure (empty only when passing).
notes: your reasoning summary — defend the verdict.
You may Read/Glob/Grep files in the run directory to verify. Respond ONLY via
the enforced JSON schema."""


class ProposedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    priority: int
    parent_id: str | None = None


class ContradictionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    adjudication: str
    resolution: Literal["adjudicated", "needs_investigation"]


class CloseQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    reason: str


class EvaluatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    unmet_criteria: list[str]
    contradictions: list[ContradictionFinding]
    new_questions: list[ProposedQuestion]
    close_questions: list[CloseQuestion]
    notes: str


def build_system_prompt(profile) -> str:
    """Stable per-run prompt: the default-FAIL gate + the profile's rubric."""
    return (
        _SYSTEM_PROMPT
        + f"\n\n# Domain rubric (profile: {profile.name}) — additional demands\n"
        + profile.rubric()
    )


def _budget_status(
    run: Runspace, settings: Settings, ledger: Ledger, cycle: int
) -> str:
    return (
        f"- cycles: {cycle} of max {settings.max_cycles}\n"
        f"- spend: ${ledger.spend_usd:.2f} of max ${settings.max_budget_usd:.2f}\n"
        f"- active wall hours: {run.wall_hours():.2f} of max {settings.max_wall_hours:.2f}"
    )


def _build_user_prompt(
    run: Runspace, settings: Settings, ledger: Ledger, cycle: int
) -> str:
    plan = (run.root / PLAN_FILE).read_text(encoding="utf-8")
    questions = run.load_questions()
    sources = run.load_sources()
    return (
        f"# Research question\n{run.meta.question}\n\n"
        f"# Run budget status (weigh your stopping discipline against this)\n"
        f"{_budget_status(run, settings, ledger, cycle)}\n\n"
        f"# Research plan\n{plan}\n\n"
        f"# Question ledger\n{common.questions_digest(questions)}\n\n"
        f"# Source registry\n{common.sources_digest(sources)}\n\n"
        f"# Findings (full text)\n{common.findings_digest(run, full_bodies=True)}\n\n"
        f"# Decisions logged so far\n"
        + "\n".join(f"- {d}" for d in run.decisions() or ["(none)"])
    )


def _apply_output(
    run: Runspace, output: EvaluatorOutput, cycle: int
) -> tuple[bool, str, list[str], list[str]]:
    """Apply closes + new questions deterministically; enforce invariant 2.
    Returns (passed, notes, added_ids, closed_ids)."""
    questions = run.load_questions()

    closed_ids: list[str] = []
    for close in output.close_questions:
        question = questions.get(close.id)  # raises StateError if unknown
        if question.status == "resolved":
            raise EvalError(
                f"evaluator tried to close {close.id}, which is already resolved"
            )
        question.status = "resolved"  # closed-as-immaterial; no finding attached
        closed_ids.append(close.id)
        run.log_decision(
            f"evaluator (cycle {cycle}) closed {close.id} as immaterial: {close.reason}"
        )

    added_ids: list[str] = []
    for proposed in output.new_questions:
        common.check_priority(proposed.priority, EvalError, f"new question {proposed.question!r}")
        if proposed.parent_id is not None:
            questions.get(proposed.parent_id)
        new_id = common.next_question_id(questions)
        questions.root.append(
            OpenQuestion(
                id=new_id,
                question=proposed.question,
                priority=proposed.priority,
                parent_id=proposed.parent_id,
                created_by="evaluator",
            )
        )
        added_ids.append(new_id)

    if closed_ids or added_ids:
        run.save_questions(questions)

    # Belt and braces on invariant 2: a "pass" while questions remain
    # unresolved is structurally impossible, whatever the model says.
    unresolved = [q.id for q in questions.root if q.status != "resolved"]
    passed = output.passed
    notes = output.notes
    if passed and unresolved:
        passed = False
        notes += (
            f"\n\n[engine] pass overridden: {len(unresolved)} unresolved "
            f"questions remain ({', '.join(unresolved)})."
        )
        run.log_decision(
            f"evaluator pass at cycle {cycle} overridden by engine: "
            f"unresolved questions {', '.join(unresolved)}"
        )
    return passed, notes, added_ids, closed_ids


def run(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    profile = get_profile(run.meta.profile)
    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="evaluator",
        role=_ROLE,
        system_prompt=build_system_prompt(profile),
        user_prompt=_build_user_prompt(run, settings, ledger, cycle),
        tools=_TOOLS,
        output_model=EvaluatorOutput,
    )
    output: EvaluatorOutput = spawn.structured

    passed, notes, added_ids, closed_ids = _apply_output(run, output, cycle)

    contradiction_lines = [
        f"{c.description} — ADJUDICATION [{c.resolution}]: {c.adjudication}"
        for c in output.contradictions
    ]
    verdict = Verdict(
        passed=passed,
        unmet_criteria=output.unmet_criteria,
        contradictions=contradiction_lines,
        new_questions=[p.question for p in output.new_questions],
        notes=notes,
    )
    run.write_verdict(cycle, verdict)
    run.log(
        f"evaluator (cycle {cycle}): {'PASS' if passed else 'FAIL'}"
        + (f", opened {', '.join(added_ids)}" if added_ids else "")
        + (f", closed {', '.join(closed_ids)}" if closed_ids else "")
        + (
            f", {len(output.contradictions)} contradictions "
            f"({sum(1 for c in output.contradictions if c.resolution == 'adjudicated')} adjudicated)"
            if output.contradictions
            else ""
        )
    )

    role_cfg = settings.roles[_ROLE]
    return SessionResult(
        session_type="evaluator",
        model=role_cfg.model,
        endpoint=role_cfg.endpoint,
        input_tokens=spawn.input_tokens,
        output_tokens=spawn.output_tokens,
        cached_tokens=spawn.cached_tokens,
        usd=spawn.usd,
        wall_seconds=spawn.wall_seconds,
        summary=("PASS" if passed else "FAIL")
        + (f" +{len(added_ids)} opened" if added_ids else "")
        + (f" -{len(closed_ids)} closed" if closed_ids else "")
        + f" ({spawn.num_turns} turns)",
    )
