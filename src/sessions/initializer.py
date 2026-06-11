"""Initializer session (Opus): QUESTION.md -> PLAN.md + open_questions.yaml
(CLAUDE.md §6). No tools — pure decomposition. The model returns structure;
this module writes the state files."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.ledger import Ledger
from src.runspace import PLAN_FILE, Runspace
from src.sessions import common
from src.sessions.base import PlanningError, SessionResult, run_role_session
from src.settings import Settings
from src.state import OpenQuestion, QuestionList

_ROLE = "initializer"

_SYSTEM_PROMPT = """\
You are the INITIALIZER session of an autonomous, multi-hour research engine.
You run exactly once, at the start of a run. Downstream, amnesiac WORKER
sessions will each investigate ONE of your open questions using web search,
and an adversarial EVALUATOR will refuse to conclude until every question is
resolved with source-backed findings.

Your job, given one research question:
1. plan_markdown — a research plan in markdown: scope, what conclusive looks
   like, the angles of attack, likely source types, known pitfalls.
2. questions — 3 to 6 open questions that decompose the research question.

Rules for questions:
- Each must be independently investigable through web research by a worker
  that knows nothing except that question and your plan.
- Cover breadth first: together they must span the research question.
- No overlapping or duplicate questions.
- priority is an integer 1-5; 5 = most load-bearing for the final answer.

You have NO tools. Respond ONLY via the enforced JSON schema."""


class PlannedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    priority: int


class InitializerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_markdown: str
    questions: list[PlannedQuestion]


def run(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    user_prompt = (
        f"Research question:\n\n{run.meta.question}\n\n"
        f"Active research profile: {run.meta.profile}\n"
        "Constraints: the run is budget- and time-bounded, so prefer fewer, "
        "sharper questions over many shallow ones."
    )
    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="initializer",
        role=_ROLE,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=[],
        output_model=InitializerOutput,
    )
    output: InitializerOutput = spawn.structured

    if not output.questions:
        raise PlanningError("initializer returned zero open questions")
    if not output.plan_markdown.strip():
        raise PlanningError("initializer returned an empty plan")

    questions = QuestionList([])
    for planned in output.questions:
        common.check_priority(planned.priority, PlanningError, f"question {planned.question!r}")
        questions.root.append(
            OpenQuestion(
                id=common.next_question_id(questions),
                question=planned.question,
                priority=planned.priority,
                created_by="initializer",
            )
        )

    # Evidence lenses (orthogonal axis): each active lens contributes seed
    # questions on its own track (docs/COMMUNITY_LENS_SPEC.md). No-op when
    # settings.lenses is empty — the default factual-only run is unchanged.
    lens_count = 0
    if settings.lenses:
        from src.lenses import get_lens

        for lens_name in settings.lenses:
            lens = get_lens(lens_name)
            for q_text, prio in lens.seed_questions(run.meta.question):
                common.check_priority(prio, PlanningError, f"{lens_name} seed")
                questions.root.append(
                    OpenQuestion(
                        id=common.next_question_id(questions),
                        question=q_text,
                        priority=prio,
                        created_by="initializer",
                        track=lens.track(),
                    )
                )
                lens_count += 1

    run.save_questions(questions)
    run.write_text(PLAN_FILE, output.plan_markdown.strip() + "\n")
    lens_note = f" (+{lens_count} lens)" if lens_count else ""
    run.log(
        f"initializer: wrote PLAN.md + {len(questions.root)} open questions{lens_note}"
    )

    role_cfg = settings.roles[_ROLE]
    return SessionResult(
        session_type="initializer",
        model=role_cfg.model,
        endpoint=role_cfg.endpoint,
        input_tokens=spawn.input_tokens,
        output_tokens=spawn.output_tokens,
        cached_tokens=spawn.cached_tokens,
        usd=spawn.usd,
        wall_seconds=spawn.wall_seconds,
        summary=f"plan + {len(questions.root)} questions ({spawn.num_turns} turns)",
    )
