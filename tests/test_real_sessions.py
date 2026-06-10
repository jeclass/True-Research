"""Deterministic guards of the real (sdk-backend) session modules — all
testable with zero LLM calls."""

from pathlib import Path

import pytest
import yaml

from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions import common, synthesizer, worker
from src.sessions.base import SynthesisError, WorkerError
from src.settings import Settings
from src.state import (
    FindingMeta,
    OpenQuestion,
    QuestionList,
    SourceRecord,
    SourceRegistry,
    utcnow,
)
from tests.conftest import BASE_CONFIG


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw["session"]["backend"] = "sdk"
    return Settings.model_validate(raw)


@pytest.fixture
def run(tmp_path: Path):
    r = Runspace.create(tmp_path / "runs", "test question", "general")
    yield r
    r.release_lock()


def _register_source(run: Runspace, source_id: str) -> None:
    registry = run.load_sources()
    registry.root[source_id] = SourceRecord(
        url=f"https://example.org/{source_id}",
        title=source_id,
        kind="web",
        credibility=80,
        retrieved_at=utcnow(),
    )
    run.save_sources(registry)


def test_merge_sources_rejects_id_collision_with_different_url(run):
    _register_source(run, "src-a")
    with pytest.raises(WorkerError, match="collision"):
        common.merge_sources(
            run,
            [{"id": "src-a", "url": "https://other.org", "title": "t",
              "kind": "web", "credibility": 50, "notes": ""}],
            WorkerError,
        )


def test_merge_sources_rejects_bad_id_and_credibility(run):
    with pytest.raises(WorkerError, match="does not match"):
        common.merge_sources(
            run,
            [{"id": "SRC_BAD!", "url": "https://x.org", "title": "t",
              "kind": "web", "credibility": 50, "notes": ""}],
            WorkerError,
        )
    with pytest.raises(WorkerError, match="credibility"):
        common.merge_sources(
            run,
            [{"id": "src-ok", "url": "https://x.org", "title": "t",
              "kind": "web", "credibility": 101, "notes": ""}],
            WorkerError,
        )


def test_next_question_id_continues_numbering():
    questions = QuestionList(
        [
            OpenQuestion(id="q-001", question="a", priority=3, created_by="initializer"),
            OpenQuestion(id="q-007", question="b", priority=3, created_by="evaluator"),
        ]
    )
    assert common.next_question_id(questions) == "q-008"


def test_worker_apply_resolved_rejects_citationless_finding(run):
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="A claim with no citation.", confidence=0.9),
        sources=[],
        progress_note="n",
    )
    with pytest.raises(WorkerError, match="no \\[src-"):
        worker._apply_resolved(run, target, output, cycle=1)


def test_worker_apply_resolved_rejects_unregistered_citation(run):
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Claim. [src-ghost]", confidence=0.9),
        sources=[],
        progress_note="n",
    )
    with pytest.raises(WorkerError, match="src-ghost"):
        worker._apply_resolved(run, target, output, cycle=1)


def test_worker_apply_resolved_happy_path_writes_state(run):
    target = OpenQuestion(id="q-001", question="x", priority=5, created_by="initializer")
    run.save_questions(QuestionList([target]))
    output = worker.WorkerOutput(
        outcome="resolved",
        finding=worker.ProposedFinding(body_markdown="Claim. [src-a]", confidence=0.8),
        sources=[
            worker.ProposedSource(
                id="src-a", url="https://example.org/a", title="A", kind="web",
                credibility=85,
            )
        ],
        progress_note="n",
    )
    summary = worker._apply_resolved(run, target, output, cycle=2)
    assert "q-001-c02" in summary
    questions = run.load_questions()
    assert questions.get("q-001").status == "resolved"
    assert questions.get("q-001").resolved_by_finding == "q-001-c02"
    meta, body = run.load_findings()["q-001-c02"]
    assert meta.source_ids == ["src-a"] and "[src-a]" in body
    assert "src-a" in run.load_sources().root


def test_synthesizer_without_findings_needs_no_model(run, settings, tmp_path):
    """No findings -> honest empty report, zero LLM calls, partial banner."""
    run.mark_finishing("budget")
    result = synthesizer.run(run, settings, 0, Ledger(run))
    report = (run.root / "REPORT.md").read_text()
    assert "PARTIAL REPORT" in report and "budget" in report
    assert "nothing to report" in report.lower()
    assert result.usd == 0.0


def test_orphaned_in_progress_question_is_picked_first():
    questions = QuestionList(
        [
            OpenQuestion(id="q-001", question="orphan", priority=2,
                         created_by="initializer", status="in_progress"),
            OpenQuestion(id="q-002", question="fresh", priority=5,
                         created_by="initializer", status="open"),
        ]
    )
    target = common.pick_target_question(questions)
    assert target is not None and target.id == "q-001"  # orphan beats higher-priority open


def test_synthesizer_citation_regex_matches_engine_convention():
    text = "Claim one [src-bmj-2024]. Claim two [src-a][src-b]. Not a cite [q-001]."
    assert common.CITATION_RE.findall(text) == ["src-bmj-2024", "src-a", "src-b"]
