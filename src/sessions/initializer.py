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
2. questions — {count_line}

Rules for questions:
- Each must be independently investigable through web research by a worker
  that knows nothing except that question and your plan.
- Cover breadth first: together they must span the research question.
- No overlapping or duplicate questions.
- priority is an integer 1-5; 5 = most load-bearing for the final answer.
{comprehensive_note}
You have NO tools. Respond ONLY via the enforced JSON schema."""


def build_system_prompt(seed_target: int) -> str:
    """Scale the initializer's decomposition by the question-tree seed target:
    normal runs get a tight 3–6 spread; comprehensive runs (high target) get a
    broad, deliberately-fragmentable facet set (item 2)."""
    if seed_target > 7:
        lo = max(6, seed_target - 4)
        count_line = (
            f"{lo} to {seed_target} open questions that decompose the research\n"
            "   question for a COMPREHENSIVE, multi-hour investigation."
        )
        comprehensive_note = (
            "\nThis is a COMPREHENSIVE run — cover the FULL breadth of every "
            "major facet. Where a facet is itself broad, phrase it so a worker "
            "will decompose it further; the engine fragments broad questions "
            "into sub-questions automatically, so do not pre-expand them. Favor "
            "complete coverage over a short list.\n"
        )
    else:
        count_line = "3 to {0} open questions that decompose the research question.".format(
            seed_target
        )
        comprehensive_note = ""
    return _SYSTEM_PROMPT.format(
        count_line=count_line, comprehensive_note=comprehensive_note
    )


class PlannedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    priority: int


class InitializerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_markdown: str
    questions: list[PlannedQuestion]


def run(run: Runspace, settings: Settings, cycle: int, ledger: Ledger) -> SessionResult:
    seed_target = settings.question_tree.seed_target
    constraint = (
        "Constraints: this is a COMPREHENSIVE run with a large budget — favor "
        "thorough breadth across every facet over a short list."
        if seed_target > 7
        else "Constraints: the run is budget- and time-bounded, so prefer "
        "fewer, sharper questions over many shallow ones."
    )
    user_prompt = (
        f"Research question:\n\n{run.meta.question}\n\n"
        f"Active research profile: {run.meta.profile}\n"
        f"{constraint}"
    )
    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=ledger,
        cycle=cycle,
        session_type="initializer",
        role=_ROLE,
        system_prompt=build_system_prompt(seed_target),
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
