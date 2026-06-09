"""Evaluator session (Opus, FRESH context): the default-FAIL quality gate
(CLAUDE.md §6, invariant 2). Sees only the files on disk; starts from FAIL;
appends new prioritized questions when it finds gaps — that is how depth
accrues. The module writes the verdict file and merges new questions
deterministically, and force-fails any pass that contradicts the state."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.ledger import Ledger
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
3. Contradictions — do findings contradict each other or themselves? List
   every contradiction you find.
4. Source quality — are sources credible, diverse (not one outlet), and recent
   enough for the topic? A conclusion resting on weak sources FAILS.
5. Sufficiency — does the set of findings actually answer the ORIGINAL
   research question, not just the open questions?

When you find gaps or contradictions, append new_questions (at most 3 per
cycle, priority 1-5, parent_id when refining an existing question) that would
close them. Make them sharp and investigable.

unmet_criteria: one entry per concrete failure (empty only when passing).
notes: your reasoning summary — defend the verdict.
You may Read/Glob/Grep files in the run directory to verify. Respond ONLY via
the enforced JSON schema."""


class ProposedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    priority: int
    parent_id: str | None = None


class EvaluatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    unmet_criteria: list[str]
    contradictions: list[str]
    new_questions: list[ProposedQuestion]
    notes: str


def _build_user_prompt(run: Runspace) -> str:
    plan = (run.root / PLAN_FILE).read_text(encoding="utf-8")
    questions = run.load_questions()
    sources = run.load_sources()
    return (
        f"# Research question\n{run.meta.question}\n\n"
        f"# Research plan\n{plan}\n\n"
        f"# Question ledger\n{common.questions_digest(questions)}\n\n"
        f"# Source registry\n{common.sources_digest(sources)}\n\n"
        f"# Findings (full text)\n{common.findings_digest(run, full_bodies=True)}\n\n"
        f"# Decisions logged so far\n"
        + "\n".join(f"- {d}" for d in run.decisions() or ["(none)"])
    )


def run(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="evaluator",
        role=_ROLE,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(run),
        tools=_TOOLS,
        output_model=EvaluatorOutput,
    )
    output: EvaluatorOutput = spawn.structured

    # Belt and braces on invariant 2: a "pass" while questions remain
    # unresolved is structurally impossible, whatever the model says.
    questions = run.load_questions()
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

    added_ids: list[str] = []
    for proposed in output.new_questions:
        common.check_priority(proposed.priority, EvalError, f"new question {proposed.question!r}")
        if proposed.parent_id is not None:
            questions.get(proposed.parent_id)  # raises StateError if unknown
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
    if added_ids:
        run.save_questions(questions)

    verdict = Verdict(
        passed=passed,
        unmet_criteria=output.unmet_criteria,
        contradictions=output.contradictions,
        new_questions=[p.question for p in output.new_questions],
        notes=notes,
    )
    run.write_verdict(cycle, verdict)
    run.log(
        f"evaluator (cycle {cycle}): {'PASS' if passed else 'FAIL'}"
        + (f", opened {', '.join(added_ids)}" if added_ids else "")
        + (f", {len(output.contradictions)} contradictions" if output.contradictions else "")
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
        + (f" +{len(added_ids)} new questions" if added_ids else "")
        + f" ({spawn.num_turns} turns)",
    )
