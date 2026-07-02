"""Web UI backend — read-only run-state layer + API routes. Hermetic: builds a
fixture runs/ dir on disk, never spawns a process or hits the network."""

import json
from pathlib import Path

import pytest

from src.webui import runs_api


def _make_run(runs_dir: Path, run_id: str, *, status="running", finished_files=False):
    d = runs_dir / run_id
    (d / "findings").mkdir(parents=True)
    (d / "verdicts").mkdir()
    (d / "run.json").write_text(json.dumps({
        "run_id": run_id, "question": "Does X cause Y?", "profile": "general",
        "created_at": "2026-07-02T00:00:00+00:00", "status": status,
        "finish_reason": "conclusive" if status == "finished" else None,
        "last_cycle": 2, "stall_count": 0, "active_seconds": 123.0,
        "final_eval_count": 1, "read_outage_streak": 0, "wave": "breadth",
    }), encoding="utf-8")
    (d / "ledger.json").write_text(json.dumps([
        {"cycle": 1, "session_type": "initializer", "model": "claude-opus-4-8",
         "endpoint": "anthropic", "input_tokens": 10, "output_tokens": 20,
         "cached_tokens": 0, "usd": 0.5, "wall_seconds": 3.0, "reconciled": True},
        {"cycle": 1, "session_type": "reader", "model": "deepseek-v4-flash",
         "endpoint": "deepseek_flash", "input_tokens": 5, "output_tokens": 5,
         "cached_tokens": 0, "usd": 0.01, "wall_seconds": 1.0, "reconciled": True},
    ]), encoding="utf-8")
    (d / "PROGRESS.md").write_text(
        "# Progress\n\n- [t] worker: did a thing\n\n## DECISIONS\n- [t] dropped a weak source\n",
        encoding="utf-8")
    (d / "open_questions.yaml").write_text(
        "- id: q-001\n  question: Does X cause Y?\n  status: resolved\n  priority: 5\n"
        "  parent_id: null\n  created_by: initializer\n  resolved_by_finding: q-001-c01\n",
        encoding="utf-8")
    (d / "sources.json").write_text(json.dumps({
        "src-a": {"url": "https://x.org/a", "title": "Study A", "kind": "paper",
                  "credibility": 90, "retrieved_at": "2026-07-02T00:00:00+00:00",
                  "notes": "RCT", "excerpts": ["X raised Y by 12%."]}}), encoding="utf-8")
    (d / "findings" / "q-001-c01.md").write_text(
        "---\nquestion_id: q-001\nsource_ids: [src-a]\nconfidence: 0.9\n"
        "verification_status: verified\n---\nX raises Y. [src-a]\n", encoding="utf-8")
    if finished_files:
        (d / "REPORT.md").write_text("# Report\n\nX raises Y [src-a].\n\n## Source registry\n"
                                     "- `src-a` — Study A (paper, credibility 90): https://x.org/a\n",
                                     encoding="utf-8")
        (d / "REPORT.pdf").write_bytes(b"%PDF-1.4 fake pdf bytes")
    return d


def test_list_runs_newest_first_with_spend(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260101-000000-aaaa")
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    out = runs_api.list_runs(runs)
    assert [r["run_id"] for r in out] == ["20260102-000000-bbbb", "20260101-000000-aaaa"]
    r0 = out[0]
    assert r0["status"] == "finished" and r0["finish_reason"] == "conclusive"
    assert r0["spend_usd"] == pytest.approx(0.51)
    assert r0["question"].startswith("Does X")
    assert r0["has_report"] is True
    assert out[1]["has_report"] is False


def test_list_runs_empty_dir_is_empty_list(tmp_path):
    assert runs_api.list_runs(tmp_path / "nope") == []


def test_get_run_detail_assembles_state(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260101-000000-aaaa")
    d = runs_api.get_run_detail(runs, "20260101-000000-aaaa")
    assert d["meta"]["run_id"] == "20260101-000000-aaaa"
    assert d["spend_usd"] == pytest.approx(0.51)
    assert d["ledger_by_type"]["reader"] == 1 and d["ledger_by_type"]["initializer"] == 1
    q = d["questions"]
    assert q[0]["id"] == "q-001" and q[0]["status"] == "resolved"
    f = d["findings"]
    assert f[0]["slug"] == "q-001-c01" and f[0]["verification_status"] == "verified"
    assert f[0]["question_id"] == "q-001"
    assert "dropped a weak source" in "\n".join(d["decisions"])


def test_get_run_detail_partial_run_no_crash(tmp_path):
    runs = tmp_path / "runs"
    d = runs / "20260101-000000-cccc"
    d.mkdir(parents=True)
    (d / "run.json").write_text(json.dumps({
        "run_id": "20260101-000000-cccc", "question": "Q", "profile": "general",
        "created_at": "2026-07-02T00:00:00+00:00", "status": "running",
        "finish_reason": None, "last_cycle": 0, "stall_count": 0,
        "active_seconds": 1.0, "final_eval_count": 0, "read_outage_streak": 0,
        "wave": "breadth"}), encoding="utf-8")
    detail = runs_api.get_run_detail(runs, "20260101-000000-cccc")
    assert detail["spend_usd"] == 0.0
    assert detail["questions"] == [] and detail["findings"] == [] and detail["sources"] == {}
    assert detail["decisions"] == []


def test_get_run_detail_unknown_id_raises_keyerror(tmp_path):
    with pytest.raises(KeyError):
        runs_api.get_run_detail(tmp_path / "runs", "does-not-exist")


def test_get_report_markdown_and_missing(tmp_path):
    runs = tmp_path / "runs"
    _make_run(runs, "20260102-000000-bbbb", status="finished", finished_files=True)
    rep = runs_api.get_report(runs, "20260102-000000-bbbb")
    assert rep["available"] is True and "## Source registry" in rep["markdown"]
    assert rep["sources"]["src-a"]["excerpts"] == ["X raised Y by 12%."]
    _make_run(runs, "20260101-000000-aaaa")
    assert runs_api.get_report(runs, "20260101-000000-aaaa")["available"] is False


def test_run_id_validation_rejects_path_traversal(tmp_path):
    for bad in ["../etc", "a/b", "..\\x", "a b", ""]:
        assert runs_api.is_valid_run_id(bad) is False
    assert runs_api.is_valid_run_id("20260102-000000-bbbb") is True
