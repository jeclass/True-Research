"""Phase 5: judge schema/metrics, eval-set integrity, bake-off overrides,
json-summary hook — all zero-LLM."""

import json
from pathlib import Path

import pytest
import yaml

from src.runspace import Runspace
from src.settings import Settings
from tests.conftest import BASE_CONFIG, only_run_dir


def _settings(tmp_path: Path, **overrides) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw.setdefault("secrets", {})
    for dotted, value in overrides.items():
        node = raw
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    return Settings.model_validate(raw)


# --- eval set integrity --------------------------------------------------------


def test_eval_questions_are_well_formed():
    from evals.run_evals import load_questions

    items = yaml.safe_load(
        (Path("evals/questions.yaml")).read_text(encoding="utf-8")
    )
    ids = [q["id"] for q in items]
    assert len(ids) == len(set(ids)), "duplicate eval ids"
    profiles = {q["profile"] for q in items}
    assert profiles <= {"general", "scientific", "visual"}
    for q in items:
        assert q["question"].strip()
        assert q.get("must_address"), f"{q['id']} has no must_address facets"
    # the quick subset spans all three profiles for a representative smoke
    quick = load_questions("quick")
    assert {q["profile"] for q in quick} == {"general", "scientific", "visual"}


# --- judge -----------------------------------------------------------------------


def test_judge_metrics_are_deterministic_from_files(tmp_path):
    from evals.judge import deterministic_metrics
    from src.ledger import Ledger
    from src.state import (
        FindingMeta,
        OpenQuestion,
        QuestionList,
        SourceRecord,
        utcnow,
    )

    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        registry = run.load_sources()
        registry.root["src-a"] = SourceRecord(
            url="https://e.org", title="A", kind="web", credibility=80,
            retrieved_at=utcnow(),
        )
        run.save_sources(registry)
        run.save_questions(
            QuestionList([
                OpenQuestion(id="q-001", question="x", priority=5,
                             created_by="initializer", status="resolved",
                             resolved_by_finding="q-001-c01"),
            ])
        )
        run.write_finding(
            "q-001-c01",
            FindingMeta(question_id="q-001", source_ids=["src-a"], confidence=0.8),
            "Claim. [src-a]",
        )
        run.write_text("REPORT.md", "# R\n\nClaim one [src-a]. Claim two [src-a].\n")
        metrics = deterministic_metrics(run, Ledger(run))
    finally:
        run.release_lock()

    assert metrics["citations_total"] == 2
    assert metrics["citations_unique"] == 1
    assert metrics["citations_unresolved"] == []
    assert metrics["citation_resolution_ok"] is True
    assert metrics["questions_resolved"] == 1


def test_judge_detects_unresolved_citation(tmp_path):
    from evals.judge import deterministic_metrics
    from src.ledger import Ledger

    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        run.write_text("REPORT.md", "# R\n\nGhost claim [src-missing].\n")
        metrics = deterministic_metrics(run, Ledger(run))
    finally:
        run.release_lock()
    assert metrics["citations_unresolved"] == ["src-missing"]
    assert metrics["citation_resolution_ok"] is False


def test_judge_scoring_helpers():
    from evals.judge import JudgeOutput, mean_score, scores_dict

    out = JudgeOutput.model_validate({
        "factual_accuracy": {"score": 8, "justification": "a"},
        "citation_accuracy": {"score": 9, "justification": "b"},
        "completeness": {"score": 6, "justification": "c"},
        "source_quality": {"score": 7, "justification": "d"},
        "tool_efficiency": {"score": 10, "justification": "e"},
        "overall_assessment": "solid",
    })
    assert scores_dict(out)["completeness"] == 6
    assert mean_score(out) == 8.0


def test_judge_score_out_of_range_rejected():
    from evals.judge import JudgeOutput
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        JudgeOutput.model_validate({
            "factual_accuracy": {"score": 11, "justification": "a"},
            "citation_accuracy": {"score": 9, "justification": "b"},
            "completeness": {"score": 6, "justification": "c"},
            "source_quality": {"score": 7, "justification": "d"},
            "tool_efficiency": {"score": 10, "justification": "e"},
            "overall_assessment": "x",
        })


# --- bake-off overrides ----------------------------------------------------------


def test_bakeoff_overrides_repoint_roles(tmp_path):
    import argparse

    from evals.run_evals import apply_overrides

    settings = _settings(tmp_path, **{"secrets": {"OLLAMA_AUTH": "ollama"}})
    args = argparse.Namespace(
        worker_model="gpt-oss:20b", worker_endpoint="local",
        reader_model=None, reader_endpoint=None,
    )
    out = apply_overrides(settings, args)
    assert out.roles["worker"].model == "gpt-oss:20b"
    assert out.roles["worker"].endpoint == "local"
    # untouched roles preserved
    assert out.roles["reader_subagent"].model == settings.roles["reader_subagent"].model


def test_bakeoff_override_to_unknown_endpoint_is_rejected(tmp_path):
    import argparse

    from evals.run_evals import apply_overrides
    from src.errors import ConfigError

    settings = _settings(tmp_path)
    args = argparse.Namespace(
        worker_model=None, worker_endpoint="nonexistent",
        reader_model=None, reader_endpoint=None,
    )
    with pytest.raises((ConfigError, ValueError)):
        apply_overrides(settings, args)


# --- judge ledger isolation ------------------------------------------------------


def test_judge_ledger_is_separate_file(tmp_path):
    from src.ledger import Ledger
    from src.state import LedgerEntry

    run = Runspace.create(tmp_path / "runs", "q", "general")
    try:
        run_ledger = Ledger(run)
        run_ledger.record(LedgerEntry(
            cycle=1, session_type="worker", model="m", endpoint="anthropic",
            input_tokens=1, output_tokens=1, cached_tokens=0, usd=0.5, wall_seconds=1,
        ))
        judge_ledger = Ledger(run, filename="judge_ledger.json")
        judge_ledger.record(LedgerEntry(
            cycle=0, session_type="judge", model="m", endpoint="anthropic",
            input_tokens=1, output_tokens=1, cached_tokens=0, usd=0.3, wall_seconds=1,
        ))
        # The run's own spend must NOT include the judge's cost.
        assert Ledger(run).spend_usd == 0.5
        assert Ledger(run, filename="judge_ledger.json").spend_usd == 0.3
    finally:
        run.release_lock()


# --- json-summary orchestrator hook ----------------------------------------------


def test_json_summary_written_on_finish(make_config, runs_dir, tmp_path):
    import driver

    summary_path = tmp_path / "summary.json"
    cfg = make_config()
    rc = driver.main([
        "q", "--config", str(cfg), "--max-cycles", "3",
        "--json-summary", str(summary_path),
    ])
    assert rc == 0
    payload = json.loads(summary_path.read_text())
    assert payload["status"] == "finished"
    assert payload["finish_reason"] == "conclusive"
    assert payload["run_id"] == only_run_dir(runs_dir).name
    assert "spend_usd" in payload and "report" in payload
