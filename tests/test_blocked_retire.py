"""Autonomous exhausted-scope retirement (2026-06-16). A real overnight run on a
hard 0DTE-options question exposed a gap: a non-seed question the worker could
never source (blocked_count climbing past 12) was never retired, so the worker
re-picked that highest-priority open question every cycle and starved the
backlog. The evaluator now retires ANY question blocked `retire_blocked_after`
times as a documented limitation (invariant 5 — never loop forever)."""

import yaml

from src.runspace import Runspace
from src.settings import Settings
from src.sessions import evaluator
from src.sessions.evaluator import EvaluatorOutput
from src.state import OpenQuestion, QuestionList
from tests.conftest import BASE_CONFIG


def _settings(tmp_path) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))  # retire_blocked_after = 4
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["secrets"] = {"ANTHROPIC_API_KEY": "sk-test", "OLLAMA_AUTH": "ollama"}
    return Settings.model_validate(raw)


def _empty_output() -> EvaluatorOutput:
    return EvaluatorOutput(
        passed=False, unmet_criteria=[], contradictions=[],
        new_questions=[], close_questions=[], notes="",
    )


def test_retires_exhausted_blocked_question_autonomously(tmp_path):
    # q-047 is blocked past the threshold and the model did NOT request a close —
    # it must still be retired so the worker stops looping on it.
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(QuestionList([
        OpenQuestion(id="q-001", question="answerable facet", priority=3, created_by="initializer"),
        OpenQuestion(id="q-047", question="unsourceable specifics", priority=5,
                     created_by="evaluator", blocked_count=5),
    ]))
    passed, _notes, _added, closed = evaluator._apply_output(
        run, _empty_output(), cycle=9, settings=_settings(tmp_path)
    )
    qs = run.load_questions()
    assert qs.get("q-047").status == "resolved"          # retired as a limitation
    assert qs.get("q-001").status == "open"              # untouched (blocked_count 0)
    assert "q-047" in closed
    assert any("RETIRED q-047" in d for d in run.decisions())
    assert not passed                                    # still unresolved work remains
    run.release_lock()


def test_does_not_retire_below_threshold(tmp_path):
    # A question blocked fewer times than the threshold is still being tried.
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(QuestionList([
        OpenQuestion(id="q-002", question="hard but not exhausted", priority=4,
                     created_by="evaluator", blocked_count=3),  # < retire_blocked_after (4)
    ]))
    evaluator._apply_output(run, _empty_output(), cycle=3, settings=_settings(tmp_path))
    assert run.load_questions().get("q-002").status == "open"
    run.release_lock()


def test_retirement_lets_run_converge(tmp_path):
    # With the only remaining work an exhausted question, retiring it clears the
    # queue so a subsequent pass is structurally allowed (no infinite loop).
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.save_questions(QuestionList([
        OpenQuestion(id="q-009", question="unsourceable", priority=5,
                     created_by="evaluator", blocked_count=6),
    ]))
    evaluator._apply_output(run, _empty_output(), cycle=7, settings=_settings(tmp_path))
    qs = run.load_questions()
    assert all(q.status == "resolved" for q in qs.root)  # queue cleared via retirement
    run.release_lock()
