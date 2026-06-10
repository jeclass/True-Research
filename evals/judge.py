"""LLM-judge scoring for the eval set (CLAUDE.md §8 Phase 5).

A FRESH Opus session (role `judge`) scores a finished run's REPORT against the
§8 rubric. The judge is told it cannot itself research — it scores only what
the report and its own sources show. Deterministic metrics (cost, cycles,
citation-resolution) come from the run files, not the model. Judge spend is
ledgered to a SEPARATE file so it never contaminates the run's own cost.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from src.ledger import Ledger
from src.runspace import REPORT_FILE, Runspace
from src.sessions.base import EvalError, run_role_session
from src.settings import Settings

_ROLE = "judge"
_JUDGE_LEDGER = "judge_ledger.json"

_CRITERIA = (
    "factual_accuracy",
    "citation_accuracy",
    "completeness",
    "source_quality",
    "tool_efficiency",
)

_SYSTEM_PROMPT = """\
You are an impartial JUDGE scoring a research report produced by an automated
engine. You did not produce it and owe it no charity. You CANNOT do your own
research — score only what the report, its cited sources, and the provided run
facts show.

Score each criterion 0-10 (10 = excellent, 0 = absent/wrong):
- factual_accuracy: are the claims correct and well-supported by the cited
  sources, with no overreach beyond what sources show?
- citation_accuracy: does every substantive claim carry a citation that
  plausibly supports it? Penalize uncited claims and citation-claim mismatch.
- completeness: does the report actually answer the research question and
  cover the listed must_address facets? A partial report that admits its gaps
  is better than one that hides them, but still incomplete.
- source_quality: are sources credible, diverse, primary where it matters, and
  appropriate for the domain?
- tool_efficiency: given the run facts (cycles, sessions, spend), did the
  engine reach its result without obvious waste or thrash? Judge proportion,
  not raw cost.

For each criterion give the score AND a one-sentence justification.
overall_assessment: 2-4 sentences on whether this is genuinely deep,
trustworthy research or shallow/overconfident.
Respond ONLY via the enforced JSON schema."""


class CriterionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=0, le=10)
    justification: str


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factual_accuracy: CriterionScore
    citation_accuracy: CriterionScore
    completeness: CriterionScore
    source_quality: CriterionScore
    tool_efficiency: CriterionScore
    overall_assessment: str


def deterministic_metrics(run: Runspace, ledger: Ledger) -> dict:
    """Facts from the run files — not the model's opinion."""
    report = (run.root / REPORT_FILE).read_text(encoding="utf-8")
    sources = run.load_sources()
    cited = re.findall(r"\[(src-[a-z0-9][a-z0-9-]{0,60})\]", report)
    unresolved = sorted({c for c in cited if c not in sources.root})
    questions = run.load_questions()
    by_type: dict[str, int] = {}
    for entry in ledger.entries:
        by_type[entry.session_type] = by_type.get(entry.session_type, 0) + 1
    return {
        "finish_reason": run.meta.finish_reason,
        "cycles": run.last_cycle(),
        "spend_usd": round(ledger.spend_usd, 4),
        "sessions_by_type": by_type,
        "questions_total": len(questions.root),
        "questions_resolved": sum(1 for q in questions.root if q.status == "resolved"),
        "sources_registered": len(sources.root),
        "citations_total": len(cited),
        "citations_unique": len(set(cited)),
        "citations_unresolved": unresolved,  # MUST be [] — invariant 3
        "citation_resolution_ok": not unresolved,
    }


def judge_run(
    run: Runspace, settings: Settings, must_address: list[str]
) -> tuple[JudgeOutput, dict]:
    """Score a finished run. Returns (judge scores, deterministic metrics)."""
    metrics = deterministic_metrics(run, ledger=Ledger(run))
    report = (run.root / REPORT_FILE).read_text(encoding="utf-8")
    sources_text = run.load_sources().model_dump_json(indent=2)

    user_prompt = (
        f"# Research question\n{run.meta.question}\n\n"
        f"# Facets the report must address (must_address)\n"
        + "\n".join(f"- {m}" for m in must_address)
        + f"\n\n# Run facts (deterministic — trust these over the report's claims "
        f"about itself)\n{json.dumps(metrics, indent=2)}\n\n"
        f"# Source registry\n{sources_text}\n\n"
        f"# REPORT under review\n{report}\n"
    )

    judge_ledger = Ledger(run, filename=_JUDGE_LEDGER)
    spawn = run_role_session(
        run=run,
        settings=settings,
        ledger=judge_ledger,
        cycle=0,
        session_type="judge",
        role=_ROLE,
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tools=["Read", "Glob", "Grep"],
        output_model=JudgeOutput,
    )
    output: JudgeOutput = spawn.structured
    metrics["judge_cost_usd"] = round(judge_ledger.spend_usd, 4)
    return output, metrics


def scores_dict(judge: JudgeOutput) -> dict[str, int]:
    return {c: getattr(judge, c).score for c in _CRITERIA}


def mean_score(judge: JudgeOutput) -> float:
    scores = scores_dict(judge)
    return round(sum(scores.values()) / len(scores), 2)
