"""Verification wave (docs/COMPREHENSIVE_RESEARCH_SPEC.md §3): the engine-built
report section + the driver phase, with the verifier mocked. Zero LLM."""

from pathlib import Path

import yaml
from rich.console import Console

import driver
from src.ledger import Ledger
from src.runspace import Runspace
from src.sessions import synthesizer
from src.settings import Settings
from src.state import FindingMeta
from tests.conftest import BASE_CONFIG


def _settings(tmp_path: Path, **dotted) -> Settings:
    raw = yaml.safe_load(yaml.safe_dump(BASE_CONFIG))
    raw["runs_dir"] = str(tmp_path / "runs")
    raw.setdefault("secrets", {})
    for key, value in dotted.items():
        node = raw
        *parents, leaf = key.split(".")
        for parent in parents:
            node = node[parent]
        node[leaf] = value
    return Settings.model_validate(raw)


def _finding(slug, status="unverified", note="", conf=0.8, track="factual"):
    meta = FindingMeta(
        question_id="q-001", source_ids=["src-a"], confidence=conf, track=track,
        verification_status=status, verification_note=note,
    )
    return meta, f"Body of {slug} [src-a]."


def test_verification_section_lists_refuted_and_counts():
    factual = {
        "f1": _finding("f1", "verified"),
        "f2": _finding("f2", "refuted", "contradicted by a 2024 RCT"),
        "f3": _finding("f3", "unverified"),
    }
    sec = synthesizer._verification_section(factual)
    assert "## Verification" in sec
    assert "1 survived" in sec and "1 were" in sec
    assert "f2" in sec and "contradicted by a 2024 RCT" in sec
    assert "f3" not in sec  # unverified findings are not listed


def test_verification_section_empty_when_nothing_checked():
    assert synthesizer._verification_section({"f1": _finding("f1", "unverified")}) == ""


def test_verify_phase_noop_when_disabled(tmp_path, monkeypatch):
    s = _settings(tmp_path)  # verification.enabled = False
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("f1", *_finding("f1"))
    import src.sessions.verifier as v

    calls = {"n": 0}
    monkeypatch.setattr(v, "verify_finding", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    driver._verify_phase(run, s, Ledger(run), Console())
    assert calls["n"] == 0
    run.release_lock()


def test_verify_phase_writes_status_and_respects_min_confidence(tmp_path, monkeypatch):
    s = _settings(tmp_path, **{"verification.enabled": True, "session.backend": "sdk"})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("f1", *_finding("f1", conf=0.9))   # load-bearing
    run.write_finding("f2", *_finding("f2", conf=0.3))   # below min_confidence 0.6
    import src.sessions.verifier as v

    monkeypatch.setattr(v, "verify_finding", lambda *a, **k: ("refuted", "independent check contradicts it"))
    driver._verify_phase(run, s, Ledger(run), Console())
    fs = run.load_findings()
    assert fs["f1"][0].verification_status == "refuted"
    assert fs["f1"][0].verification_note == "independent check contradicts it"
    assert fs["f2"][0].verification_status == "unverified"  # skipped (low confidence)
    run.release_lock()


def test_verify_phase_stops_at_budget(tmp_path, monkeypatch):
    s = _settings(tmp_path, **{"verification.enabled": True, "session.backend": "sdk",
                               "max_budget_usd": 0.0})
    run = Runspace.create(tmp_path / "runs", "q", "general")
    run.write_finding("f1", *_finding("f1", conf=0.9))
    import src.sessions.verifier as v

    calls = {"n": 0}
    monkeypatch.setattr(v, "verify_finding",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), ("verified", "")) [1])
    driver._verify_phase(run, s, Ledger(run), Console())
    assert calls["n"] == 0  # budget 0 => halted before any verify
    assert any("budget breaker" in d for d in run.decisions())
    run.release_lock()
